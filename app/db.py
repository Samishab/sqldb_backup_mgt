"""Control-panel metadata store (separate SQLite file - never inside a database being backed up)."""
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
DB_FILE = DATA / "controlpanel.db"
_lock = threading.Lock()

KINDS = ("connections", "destinations", "schedules")

DEFAULT_SETTINGS = {
    "backup_dir": str(DATA / "backups"),
    "stale_hours": "36",
    "notify_on": "failure",  # failure | all | none
    "rclone_path": "rclone",
    "promote_foreign_full": "1",
    "history_days": "0",
    "telegram_token": "", "telegram_chat": "",
    "smtp_host": "", "smtp_port": "587", "smtp_user": "", "smtp_pass": "",
    "smtp_from": "", "smtp_to": "", "smtp_tls": "1",
    "webhook_url": "",
}


def now():
    return datetime.now().isoformat(timespec="seconds")


def _run(sql, args=(), fetch=True):
    with _lock:
        c = sqlite3.connect(DB_FILE, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            cur = c.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()] if fetch else []
            c.commit()
            return rows if fetch else cur.lastrowid
        finally:
            c.close()


def q(sql, args=()):
    return _run(sql, args, True)


def x(sql, args=()):
    return _run(sql, args, False)


def init():
    for k in KINDS:
        x(f"CREATE TABLE IF NOT EXISTS {k}(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, data TEXT, created TEXT)")
    x("""CREATE TABLE IF NOT EXISTS runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, schedule_id INTEGER, schedule_name TEXT,
        connection_id INTEGER, db TEXT, type TEXT, trigger TEXT, status TEXT,
        started TEXT, finished TEXT, size INTEGER DEFAULT 0, file TEXT, verified INTEGER DEFAULT 0,
        uploads TEXT DEFAULT '[]', error TEXT, log TEXT DEFAULT '', deleted INTEGER DEFAULT 0)""")
    x("CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT)")
    x("CREATE TABLE IF NOT EXISTS seq(k TEXT PRIMARY KEY, v INTEGER)")
    have = {r["name"] for r in q("PRAGMA table_info(runs)")}
    for col, typ in (("full_seq", "INTEGER"), ("seq_no", "INTEGER"), ("set_guid", "TEXT")):
        if col not in have:
            x(f"ALTER TABLE runs ADD COLUMN {col} {typ}")
    x("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, action TEXT, detail TEXT)")
    # a server restart kills in-flight jobs
    x("UPDATE runs SET status='failed', error='توقف الخدمة أثناء التنفيذ', finished=? WHERE status='running'", (now(),))


# ---- generic JSON items ----
def _item(r):
    d = json.loads(r["data"] or "{}")
    d.update(id=r["id"], name=r["name"])
    return d


def list_items(kind):
    return [_item(r) for r in q(f"SELECT * FROM {kind} ORDER BY id")]


def get_item(kind, id_):
    r = q(f"SELECT * FROM {kind} WHERE id=?", (id_,))
    return _item(r[0]) if r else None


def save_item(kind, id_, body):
    body = dict(body)
    body.pop("id", None)
    name = body.pop("name", "") or "بدون اسم"
    if id_:
        x(f"UPDATE {kind} SET name=?, data=? WHERE id=?", (name, json.dumps(body, ensure_ascii=False), id_))
        return id_
    return x(f"INSERT INTO {kind}(name,data,created) VALUES(?,?,?)", (name, json.dumps(body, ensure_ascii=False), now()))


def delete_item(kind, id_):
    x(f"DELETE FROM {kind} WHERE id=?", (id_,))


def next_seq(key, start=1):
    """Atomic persistent counter: returns `start` the first time, then +1 on every call. Never resets."""
    return q("INSERT INTO seq(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=v+1 RETURNING v", (key, start))[0]["v"]


# ---- settings / audit ----
def get_setting(k):
    r = q("SELECT v FROM settings WHERE k=?", (k,))
    return r[0]["v"] if r else DEFAULT_SETTINGS.get(k, "")


def all_settings():
    s = dict(DEFAULT_SETTINGS)
    s.update({r["k"]: r["v"] for r in q("SELECT * FROM settings") if r["k"] in DEFAULT_SETTINGS})
    return s


def set_setting(k, v):
    x("INSERT INTO settings(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def audit(action, detail=""):
    x("INSERT INTO audit(ts,action,detail) VALUES(?,?,?)", (now(), action, detail))
