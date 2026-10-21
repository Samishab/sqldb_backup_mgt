from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import alerts, db, engine

sched = BackgroundScheduler()
DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def window_trigger(t):
    """Run every N minutes/hours inside one or more daily periods, on chosen weekdays (none = every day).
    A period whose end is before its start is split at midnight."""
    days = ",".join(d for d in t.get("days") or [] if d in DAYS) or None
    step = max(1, int(t.get("every") or 1))
    step_min = step * 60 if t.get("unit") == "hours" else step
    trigs = []
    for p in t.get("periods") or [{"from": "00:00", "to": "23:59"}]:
        a, b = _mins(p["from"]), _mins(p["to"])
        for lo, hi in ([(a, b)] if a <= b else [(a, 1439), (0, b)]):
            by_hour, m = {}, lo
            while m <= hi:
                by_hour.setdefault(m // 60, []).append(m % 60)
                m += step_min
            for h, mins in by_hour.items():
                kw = {"hour": h, "minute": ",".join(map(str, mins))}
                if days:
                    kw["day_of_week"] = days
                trigs.append(CronTrigger(**kw))
    if not trigs:
        raise ValueError("no periods")
    return OrTrigger(trigs)


def make_trigger(t):
    mode = t.get("mode", "daily")
    if mode == "window":
        return window_trigger(t)
    if mode == "at":
        days = ",".join(d for d in t.get("days") or [] if d in DAYS) or None
        dom = int(t.get("dom") or 0)
        trigs = []
        for hhmm in t.get("times") or ["02:00"]:
            h, m = hhmm.split(":")
            kw = {"hour": int(h), "minute": int(m)}
            if dom:
                kw["day"] = dom
            elif days:
                kw["day_of_week"] = days
            trigs.append(CronTrigger(**kw))
        return OrTrigger(trigs) if len(trigs) > 1 else trigs[0]
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


def clean_history(force_days=None):
    """Delete old run-log rows. Rows that still point to a live backup file are kept (restore and retention need
    them); only deleted-file entries, failed runs and restore logs older than the limit are removed."""
    days = int(force_days if force_days is not None else (db.get_setting("history_days") or 0))
    if days <= 0:
        return 0
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    where = "started < ? AND (deleted=1 OR status='failed' OR type='restore')"
    n = db.q(f"SELECT COUNT(*) AS n FROM runs WHERE {where}", (cutoff,))[0]["n"]
    if n:
        db.x(f"DELETE FROM runs WHERE {where}", (cutoff,))
    return n


def watchdog():
    stale = stale_report()
    key = datetime.now().strftime("%Y-%m-%d")
    if stale and db.get_setting("stale_alert_day") != key:
        db.set_setting("stale_alert_day", key)
        alerts.notify("⚠️ تنبيه: لا توجد نسخة ناجحة حديثة", "\n".join(f"- {s['db']} (آخر نسخة: {s['last'] or 'لا يوجد'})" for s in stale), False)


def start():
    sched.start()
    sync()
    sched.add_job(clean_history, CronTrigger(hour=3, minute=30), id="history", misfire_grace_time=3600)
    sched.add_job(watchdog, IntervalTrigger(minutes=30), id="watchdog", next_run_time=datetime.now() + timedelta(minutes=2))
