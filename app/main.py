import hashlib
import json
import os
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import alerts, db, engine, scheduler

STATIC = Path(__file__).parent / "static"
SESSIONS = set()
OPEN = {"/api/auth/status", "/api/auth/login", "/api/auth/setup"}

app = FastAPI(title="DB Backup Control Panel")


@app.on_event("startup")
def _start():
    db.init()
    Path(db.get_setting("backup_dir")).mkdir(parents=True, exist_ok=True)
    scheduler.start()


@app.middleware("http")
async def guard(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api/") and p not in OPEN and request.cookies.get("sid") not in SESSIONS:
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


# ------------------------------------------------------------------ auth
def _hash(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"


def _login(resp):
    sid = secrets.token_urlsafe(32)
    SESSIONS.add(sid)
    resp.set_cookie("sid", sid, httponly=True, samesite="lax", max_age=7 * 86400)


@app.get("/api/auth/status")
def auth_status(request: Request):
    return {"configured": bool(db.get_setting("password_hash")), "authed": request.cookies.get("sid") in SESSIONS}


@app.post("/api/auth/setup")
def auth_setup(resp: Response, body: dict = Body(...)):
    if db.get_setting("password_hash"):
        raise HTTPException(400, "كلمة المرور محددة مسبقًا")
    if len(body.get("password", "")) < 6:
        raise HTTPException(400, "كلمة المرور قصيرة (6 أحرف على الأقل)")
    db.set_setting("password_hash", _hash(body["password"]))
    db.audit("setup", "تعيين كلمة المرور الأولى")
    _login(resp)
    return {"ok": True}


@app.post("/api/auth/login")
def auth_login(resp: Response, body: dict = Body(...)):
    stored = db.get_setting("password_hash")
    if not stored or _hash(body.get("password", ""), stored.split("$")[0]) != stored:
        db.audit("login_failed", "")
        raise HTTPException(401, "كلمة المرور غير صحيحة")
    _login(resp)
    db.audit("login", "")
    return {"ok": True}


@app.post("/api/auth/logout")
def auth_logout(request: Request, resp: Response):
    SESSIONS.discard(request.cookies.get("sid"))
    resp.delete_cookie("sid")
    return {"ok": True}


@app.post("/api/auth/password")
def auth_password(body: dict = Body(...)):
    stored = db.get_setting("password_hash")
    if _hash(body.get("old", ""), stored.split("$")[0]) != stored:
        raise HTTPException(400, "كلمة المرور الحالية خاطئة")
    if len(body.get("new", "")) < 6:
        raise HTTPException(400, "كلمة المرور قصيرة")
    db.set_setting("password_hash", _hash(body["new"]))
    db.audit("password_changed", "")
    return {"ok": True}


# ------------------------------------------------------------------ dashboard
def _dur(r):
    if r["finished"]:
        return int((datetime.fromisoformat(r["finished"]) - datetime.fromisoformat(r["started"])).total_seconds())
    return int((datetime.now() - datetime.fromisoformat(r["started"])).total_seconds())


@app.get("/api/dashboard")
def dashboard():
    bk = "type IN ('full','diff','log')"
    runs = db.q(f"SELECT * FROM runs WHERE {bk} ORDER BY started DESC LIMIT 400")
    last_ok = next((r for r in runs if r["status"] == "success"), None)
    last = runs[0] if runs else None
    since = (datetime.now() - timedelta(days=13)).date()
    days = {(since + timedelta(days=i)).isoformat(): {"day": (since + timedelta(days=i)).isoformat(), "ok": 0, "failed": 0, "size": 0}
            for i in range(14)}
    for r in runs:
        d = days.get(r["started"][:10])
        if d and r["status"] in ("success", "failed"):
            d["ok" if r["status"] == "success" else "failed"] += 1
            d["size"] += r["size"] or 0
    per_db = {}
    for r in db.q(f"SELECT connection_id, db, type, status, started, size FROM runs WHERE {bk} AND deleted=0 ORDER BY started DESC"):
        e = per_db.setdefault((r["connection_id"], r["db"]), {"db": r["db"], "connection_id": r["connection_id"], "last_ok": None, "last_status": r["status"], "total_size": 0, "count": 0})
        if r["status"] == "success":
            e["last_ok"] = e["last_ok"] or r["started"]
            e["total_size"] += r["size"] or 0
            e["count"] += 1
    conns = {c["id"]: c["name"] for c in db.list_items("connections")}
    for e in per_db.values():
        e["connection"] = conns.get(e["connection_id"], "?")
    bdir = db.get_setting("backup_dir")
    Path(bdir).mkdir(parents=True, exist_ok=True)
    du = shutil.disk_usage(bdir)
    total = db.q(f"SELECT COALESCE(SUM(size),0) s, COUNT(*) c FROM runs WHERE {bk} AND status='success' AND deleted=0")[0]
    nxt = scheduler.next_runs()
    scheds = [{"id": s["id"], "name": s["name"], "next": nxt.get(s["id"])} for s in db.list_items("schedules") if s.get("enabled", True)]
    return {
        "last": last and {**last, "duration": _dur(last)},
        "last_ok": last_ok and {**last_ok, "duration": _dur(last_ok)},
        "running": db.q("SELECT id, db, type, started FROM runs WHERE status='running'"),
        "stale": scheduler.stale_report(),
        "days": list(days.values()),
        "databases": list(per_db.values()),
        "disk": {"free": du.free, "total": du.total, "dir": bdir},
        "stored": {"size": total["s"], "count": total["c"]},
        "success_rate": round(100 * sum(r["status"] == "success" for r in runs[:100]) / max(1, len(runs[:100])), 1),
        "next": sorted([s for s in scheds if s["next"]], key=lambda s: s["next"])[:5],
        "counts": {k: len(db.list_items(k)) for k in db.KINDS},
    }


# ------------------------------------------------------------------ connections / destinations
@app.post("/api/probe/connection")
def probe(body: dict = Body(...)):
    try:
        return engine.test_connection(body)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.get("/api/connections/{id_}/databases")
def conn_dbs(id_: int):
    cfg = db.get_item("connections", id_)
    try:
        return engine.list_databases(cfg)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


@app.post("/api/probe/destination")
def probe_dest(body: dict = Body(...)):
    try:
        return engine.check_destination(body)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


# ------------------------------------------------------------------ runs
@app.post("/api/schedules/{id_}/run")
def run_schedule(id_: int):
    s = db.get_item("schedules", id_)
    if not s:
        raise HTTPException(404)
    ids = [engine.start_run(s["connection_id"], n, s["type"], s.get("destinations", []), s.get("verify", True),
                            s.get("retention", {}), s, "manual") for n in s.get("databases", [])]
    db.audit("run_schedule", s["name"])
    return {"runs": ids}


@app.post("/api/backup")
def backup_now(body: dict = Body(...)):
    ids = [engine.start_run(int(body["connection_id"]), n, body.get("type", "full"), body.get("destinations", []),
                            body.get("verify", True), {}, None, "manual") for n in body["databases"]]
    db.audit("backup_now", ", ".join(body["databases"]))
    return {"runs": ids}


@app.get("/api/runs")
def runs(limit: int = 200, status: str = "", db_name: str = "", rtype: str = ""):
    sql, args = "SELECT id,schedule_name,connection_id,db,type,trigger,status,started,finished,size,file,verified,uploads,error,deleted FROM runs WHERE 1=1", []
    for col, val in (("status", status), ("db", db_name), ("type", rtype)):
        if val:
            sql += f" AND {col}=?"; args.append(val)
    out = db.q(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))
    for r in out:
        r["duration"] = _dur(r)
        r["uploads"] = json.loads(r["uploads"] or "[]")
        r["file_exists"] = bool(r["file"]) and Path(r["file"]).exists()
    return out


@app.get("/api/runs/{id_}")
def run_detail(id_: int):
    r = db.q("SELECT * FROM runs WHERE id=?", (id_,))
    if not r:
        raise HTTPException(404)
    r[0]["uploads"] = json.loads(r[0]["uploads"] or "[]")
    return r[0]


@app.delete("/api/runs/{id_}")
def delete_run(id_: int):
    r = db.q("SELECT * FROM runs WHERE id=?", (id_,))
    if not r:
        raise HTTPException(404)
    engine.delete_run_files(r[0])
    db.x("UPDATE runs SET deleted=1 WHERE id=?", (id_,))
    db.audit("run_delete", f"#{id_} {r[0]['db']}")
    return {"ok": True}


@app.post("/api/runs/{id_}/restore")
def restore(id_: int, body: dict = Body(...)):
    name = (body.get("new_name") or "").strip()
    if not name:
        raise HTTPException(400, "اسم القاعدة الجديدة مطلوب")
    db.audit("restore" if not body.get("test") else "restore_test", f"#{id_} → {name}")
    return {"run": engine.start_restore(id_, name, bool(body.get("test")))}


# ------------------------------------------------------------------ settings / audit
@app.get("/api/settings")
def get_settings():
    return db.all_settings()


@app.put("/api/settings")
def put_settings(body: dict = Body(...)):
    for k, v in body.items():
        if k in db.DEFAULT_SETTINGS:
            db.set_setting(k, v)
    db.audit("settings_update", ", ".join(body))
    return {"ok": True}


@app.post("/api/alerts/test")
def alerts_test():
    sent, errs = alerts.send_sync("🔔 اختبار التنبيهات", "رسالة تجريبية من لوحة النسخ الاحتياطي")
    return {"sent": sent, "errors": errs}


@app.get("/api/audit/log")
def audit_log():
    return db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 300")


# ------------------------------------------------------------------ CRUD
def _kind(kind):
    if kind not in db.KINDS:
        raise HTTPException(404)
    return kind


@app.get("/api/{kind}")
def list_kind(kind: str):
    if kind not in db.KINDS:
        raise HTTPException(404)
    items = db.list_items(kind)
    if kind == "schedules":
        nxt = scheduler.next_runs()
        for s in items:
            s["next"] = nxt.get(s["id"])
    return items


@app.post("/api/{kind}")
def create_kind(kind: str, body: dict = Body(...)):
    i = db.save_item(_kind(kind), None, body)
    db.audit(f"{kind}_create", body.get("name", ""))
    if kind == "schedules":
        scheduler.sync()
    return {"id": i}


@app.put("/api/{kind}/{id_}")
def update_kind(kind: str, id_: int, body: dict = Body(...)):
    db.save_item(_kind(kind), id_, body)
    db.audit(f"{kind}_update", body.get("name", ""))
    if kind == "schedules":
        scheduler.sync()
    return {"id": id_}


@app.delete("/api/{kind}/{id_}")
def delete_kind(kind: str, id_: int):
    it = db.get_item(_kind(kind), id_)
    db.delete_item(kind, id_)
    db.audit(f"{kind}_delete", it["name"] if it else str(id_))
    if kind == "schedules":
        scheduler.sync()
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
