from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import alerts, db, engine

sched = BackgroundScheduler()
DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def make_trigger(t):
    mode = t.get("mode", "daily")
    hh, mm = (t.get("time") or "02:00").split(":")
    if mode == "interval":
        every = max(1, int(t.get("every") or 1))
        unit = t.get("unit", "hours")
        return IntervalTrigger(**{unit: every})
    if mode == "daily":
        return CronTrigger(hour=int(hh), minute=int(mm))
    if mode == "weekly":
        days = ",".join(d for d in t.get("days", ["sun"]) if d in DAYS) or "sun"
        return CronTrigger(day_of_week=days, hour=int(hh), minute=int(mm))
    if mode == "monthly":
        return CronTrigger(day=int(t.get("day") or 1), hour=int(hh), minute=int(mm))
    if mode == "cron":
        return CronTrigger.from_crontab(t["expr"])
    raise ValueError("trigger mode")


def fire(schedule_id):
    s = db.get_item("schedules", schedule_id)
    if not s or not s.get("enabled", True):
        return
    for name in s.get("databases", []):
        engine.start_run(s["connection_id"], name, s["type"], s.get("destinations", []),
                         s.get("verify", True), s.get("retention", {}), s, "schedule")


def sync():
    for j in sched.get_jobs():
        if j.id.startswith("s"):
            j.remove()
    for s in db.list_items("schedules"):
        if s.get("enabled", True):
            try:
                sched.add_job(fire, make_trigger(s["trigger"]), args=[s["id"]], id=f"s{s['id']}",
                              misfire_grace_time=3600, coalesce=True)
            except Exception as e:  # noqa: BLE001
                db.audit("schedule_error", f"{s['name']}: {e}")


def next_runs():
    return {int(j.id[1:]): j.next_run_time.isoformat(timespec="seconds") for j in sched.get_jobs()
            if j.id.startswith("s") and j.next_run_time}


def stale_report():
    """Enabled scheduled databases whose last successful backup is older than the threshold."""
    limit = timedelta(hours=float(db.get_setting("stale_hours") or 36))
    out = []
    for s in db.list_items("schedules"):
        if not s.get("enabled", True) or s["type"] == "log":
            continue
        for name in s.get("databases", []):
            r = db.q("SELECT started FROM runs WHERE connection_id=? AND db=? AND status='success' AND type IN "
                     "('full','diff') AND deleted=0 ORDER BY started DESC LIMIT 1", (s["connection_id"], name))
            last = datetime.fromisoformat(r[0]["started"]) if r else None
            if last is None or datetime.now() - last > limit:
                out.append({"db": name, "last": r[0]["started"] if r else None})
    return out


def watchdog():
    stale = stale_report()
    key = datetime.now().strftime("%Y-%m-%d")
    if stale and db.get_setting("stale_alert_day") != key:
        db.set_setting("stale_alert_day", key)
        alerts.notify("⚠️ تنبيه: لا توجد نسخة ناجحة حديثة", "\n".join(f"- {s['db']} (آخر نسخة: {s['last'] or 'لا يوجد'})" for s in stale), False)


def start():
    sched.start()
    sync()
    sched.add_job(watchdog, IntervalTrigger(minutes=30), id="watchdog", next_run_time=datetime.now() + timedelta(minutes=2))
