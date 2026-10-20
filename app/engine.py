"""Backup / verify / upload / retention / restore engine."""
import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from . import alerts, db

_locks = {}
EXT = {"sqlserver": ".bak", "sqlite": ".sqlite", "mysql": ".sql.gz", "postgres": ".dump"}
NOWIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def safe(s):
    return re.sub(r"[^\w\-.]+", "_", s)


def qn(name):
    return "[" + name.replace("]", "]]") + "]"


def ql(s):
    return "N'" + str(s).replace("'", "''") + "'"


# ---------------------------------------------------------------- SQL Server
def sql_connect(cfg, timeout=15):
    import pyodbc
    drivers = pyodbc.drivers()
    drv = cfg.get("driver") or next((d for d in (
        "ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server",
        "SQL Server Native Client 11.0", "SQL Server") if d in drivers), None)
    if not drv:
        raise RuntimeError("لا يوجد ODBC Driver لـ SQL Server")
    s = f"DRIVER={{{drv}}};SERVER={cfg.get('server') or '.'};DATABASE=master;"
    s += (f"UID={cfg.get('user', '')};PWD={cfg.get('password', '')};" if cfg.get("auth") == "sql"
          else "Trusted_Connection=yes;")
    if "ODBC Driver" in drv:
        s += "TrustServerCertificate=yes;"
    return pyodbc.connect(s, autocommit=True, timeout=timeout)


def sql_exec(cfg, sql):
    cnx = sql_connect(cfg)
    try:
        cur = cnx.cursor()
        cur.execute(sql)
        while cur.nextset():
            pass
    finally:
        cnx.close()


def sql_rows(cfg, sql):
    cnx = sql_connect(cfg)
    try:
        cur = cnx.cursor()
        cur.execute(sql)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cnx.close()


# ---------------------------------------------------------------- connectors
def list_databases(cfg):
    t = cfg.get("type")
    if t == "sqlserver":
        rows = sql_rows(cfg, """SELECT d.name, d.recovery_model_desc AS recovery,
            CAST(SUM(mf.size)*8/1024.0 AS DECIMAL(18,1)) AS size_mb
            FROM sys.databases d JOIN sys.master_files mf ON mf.database_id=d.database_id
            WHERE d.state=0 AND d.name<>'tempdb' GROUP BY d.name, d.recovery_model_desc ORDER BY d.name""")
        return [{"name": r["name"], "recovery": r["recovery"], "size_mb": float(r["size_mb"])} for r in rows]
    if t == "sqlite":
        p = Path(cfg["path"])
        if not p.exists():
            raise RuntimeError("الملف غير موجود")
        return [{"name": p.stem, "size_mb": round(p.stat().st_size / 1048576, 1)}]
    return []  # mysql / postgres: names typed manually


def test_connection(cfg):
    t = cfg.get("type")
    if t == "sqlserver":
        r = sql_rows(cfg, "SELECT @@VERSION AS v")[0]["v"].splitlines()[0]
        return {"ok": True, "info": r, "databases": list_databases(cfg)}
    if t == "sqlite":
        return {"ok": True, "info": "SQLite", "databases": list_databases(cfg)}
    exe = _bin(cfg, "mysqldump" if t == "mysql" else "pg_dump")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, creationflags=NOWIN)
    if out.returncode:
        raise RuntimeError(out.stderr or "الأداة غير موجودة")
    return {"ok": True, "info": out.stdout.strip(), "databases": []}


def _bin(cfg, name):
    d = cfg.get("bin_dir")
    return str(Path(d) / name) if d else name


def do_backup(cfg, dbname, btype, path, log):
    t = cfg["type"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if t == "sqlserver":
        kind = "LOG" if btype == "log" else "DATABASE"
        diff = "DIFFERENTIAL," if btype == "diff" else ""
        base = f"BACKUP {kind} {qn(dbname)} TO DISK={ql(path)} WITH {diff}%sCHECKSUM, INIT, NAME={ql(dbname + ' ' + btype)}"
        try:
            sql_exec(cfg, base % "COMPRESSION, ")
        except Exception as e:  # noqa: BLE001 - edition without compression
            if "compression" not in str(e).lower():
                raise
            log("الضغط غير مدعوم في هذه النسخة، المحاولة بدون ضغط")
            sql_exec(cfg, base % "")
    elif t == "sqlite":
        if btype != "full":
            raise RuntimeError("SQLite يدعم النسخة الكاملة فقط")
        src, dst = sqlite3.connect(cfg["path"]), sqlite3.connect(path)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
    elif t == "mysql":
        cmd = [_bin(cfg, "mysqldump"), "-h", cfg.get("host", "localhost"), "-P", str(cfg.get("port") or 3306),
               "-u", cfg.get("user", "root"), "--single-transaction", "--routines", "--events", dbname]
        env = dict(os.environ, MYSQL_PWD=cfg.get("password", ""))
        with gzip.open(path, "wb") as f:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, creationflags=NOWIN)
            for chunk in iter(lambda: p.stdout.read(1 << 20), b""):
                f.write(chunk)
            err = p.stderr.read().decode(errors="replace")
            if p.wait():
                raise RuntimeError(err or "mysqldump failed")
    elif t == "postgres":
        env = dict(os.environ, PGPASSWORD=cfg.get("password", ""))
        r = subprocess.run([_bin(cfg, "pg_dump"), "-h", cfg.get("host", "localhost"), "-p", str(cfg.get("port") or 5432),
                            "-U", cfg.get("user", "postgres"), "-Fc", "-f", str(path), dbname],
                           capture_output=True, text=True, env=env, creationflags=NOWIN)
        if r.returncode:
            raise RuntimeError(r.stderr)
    else:
        raise RuntimeError(f"نوع غير مدعوم: {t}")


def do_verify(cfg, path):
    t = cfg["type"]
    if t == "sqlserver":
        sql_exec(cfg, f"RESTORE VERIFYONLY FROM DISK={ql(path)} WITH CHECKSUM")
    elif t == "sqlite":
        c = sqlite3.connect(path)
        try:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("integrity_check failed")
        finally:
            c.close()
    elif t == "mysql":
        with gzip.open(path, "rb") as f:
            while f.read(1 << 22):
                pass
    elif t == "postgres":
        r = subprocess.run([_bin(cfg, "pg_restore"), "-l", str(path)], capture_output=True, creationflags=NOWIN)
        if r.returncode:
            raise RuntimeError(r.stderr.decode(errors="replace"))
    if Path(path).stat().st_size == 0:
        raise RuntimeError("الملف فارغ")


# ---------------------------------------------------------------- destinations
def _rclone(args, timeout=None):
    exe = db.get_setting("rclone_path") or "rclone"
    r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout or "rclone failed").strip()[-600:])
    return r.stdout


def _remote_name(dest, rel):
    base = dest["remote"].rstrip("/")
    return f"{base}/{rel}" if not base.endswith(":") else f"{base}{rel}"


def upload(dest, src, rel):
    if dest["type"] == "local":
        target = Path(dest["path"]) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        if target.stat().st_size != Path(src).stat().st_size:
            raise RuntimeError("حجم الملف المنسوخ لا يطابق الأصل")
        return str(target)
    if dest["type"] == "rclone":
        target = _remote_name(dest, rel)
        extra = dest.get("flags", "").split()
        _rclone(["copyto", str(src), target, "--checksum", *extra])
        return target
    raise RuntimeError("نوع وجهة غير معروف")


def remove_remote(dest, target):
    if dest["type"] == "local":
        Path(target).unlink(missing_ok=True)
    elif dest["type"] == "rclone":
        _rclone(["deletefile", target])


def check_destination(dest):
    if dest["type"] == "local":
        p = Path(dest["path"])
        p.mkdir(parents=True, exist_ok=True)
        t = p / ".write_test"
        t.write_text("ok"); t.unlink()
        u = shutil.disk_usage(p)
        return {"ok": True, "info": f"متاح {u.free / 1e9:.1f} GB من {u.total / 1e9:.1f} GB", "free": u.free}
    out = _rclone(["lsd", dest["remote"]], timeout=60)
    free = ""
    try:
        free = " | " + " ".join(_rclone(["about", dest["remote"]], timeout=60).split())
    except Exception:  # noqa: BLE001 - not every backend supports "about"
        pass
    return {"ok": True, "info": f"اتصال ناجح{free}"}


# ---------------------------------------------------------------- run orchestration
def start_run(conn_id, dbname, btype, dest_ids, verify, retention, schedule=None, trigger="manual"):
    rid = db.x("INSERT INTO runs(schedule_id,schedule_name,connection_id,db,type,trigger,status,started) "
               "VALUES(?,?,?,?,?,?,'running',?)",
               (schedule["id"] if schedule else None, schedule["name"] if schedule else "نسخ يدوي",
                conn_id, dbname, btype, trigger, db.now()))
    threading.Thread(target=_execute, args=(rid, conn_id, dbname, btype, dest_ids, verify, retention), daemon=True).start()
    return rid


def _execute(rid, conn_id, dbname, btype, dest_ids, verify, retention):
    lines = []

    def log(msg):
        lines.append(f"[{datetime.now():%H:%M:%S}] {msg}")
        db.x("UPDATE runs SET log=? WHERE id=?", ("\n".join(lines), rid))

    cfg = db.get_item("connections", conn_id)
    uploads, size, path, err = [], 0, None, None
    lock = _locks.setdefault(conn_id, threading.Lock())
    try:
        if not cfg:
            raise RuntimeError("الاتصال محذوف")
        with lock:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            rel = f"{safe(dbname)}/{safe(dbname)}_{btype}_{stamp}{EXT.get(cfg['type'], '.bak')}"
            path = Path(db.get_setting("backup_dir")) / rel
            log(f"بدء نسخة {btype} للقاعدة {dbname}")
            do_backup(cfg, dbname, btype, path, log)
            size = path.stat().st_size
            db.x("UPDATE runs SET file=?, size=? WHERE id=?", (str(path), size, rid))
            log(f"اكتمل النسخ: {size / 1048576:.1f} MB")
            if verify:
                log("التحقق من سلامة النسخة...")
                do_verify(cfg, path)
                db.x("UPDATE runs SET verified=1 WHERE id=?", (rid,))
                log("التحقق ناجح ✔")
        for did in dest_ids or []:
            d = db.get_item("destinations", did)
            if not d or not d.get("enabled", True):
                continue
            try:
                log(f"رفع إلى {d['name']}...")
                uploads.append({"dest_id": did, "name": d["name"], "status": "ok", "path": upload(d, path, rel)})
                log(f"تم الرفع إلى {d['name']} ✔")
            except Exception as e:  # noqa: BLE001
                uploads.append({"dest_id": did, "name": d["name"], "status": "failed", "error": str(e)})
                log(f"فشل الرفع إلى {d['name']}: {e}")
        if any(u["status"] == "failed" for u in uploads):
            err = "فشل الرفع إلى: " + "، ".join(u["name"] for u in uploads if u["status"] == "failed")
        try:
            apply_retention(conn_id, dbname, btype, retention or {}, log)
        except Exception as e:  # noqa: BLE001
            log(f"تحذير - تنظيف النسخ القديمة: {e}")
    except Exception as e:  # noqa: BLE001
        err = str(e)
        log(f"خطأ: {e}")
    status = "failed" if err else "success"
    db.x("UPDATE runs SET status=?, finished=?, error=?, uploads=? WHERE id=?",
         (status, db.now(), err, json.dumps(uploads, ensure_ascii=False), rid))
    title = f"{'✅' if not err else '❌'} نسخ احتياطي {dbname} ({btype})"
    alerts.notify(title, err or f"نجحت النسخة - {size / 1048576:.1f} MB", not err)


# ---------------------------------------------------------------- retention
def apply_retention(conn_id, dbname, btype, ret, log=print):
    d, w, m = int(ret.get("daily") or 0), int(ret.get("weekly") or 0), int(ret.get("monthly") or 0)
    if not (d or w or m):
        return
    rows = db.q("SELECT * FROM runs WHERE connection_id=? AND db=? AND type=? AND status='success' AND deleted=0 "
                "ORDER BY started DESC", (conn_id, dbname, btype))
    if len(rows) < 2:
        return
    keep = {rows[0]["id"]}
    today = datetime.now()
    if btype == "log":  # logs form a chain: keep everything inside the daily window
        cutoff = today - timedelta(days=max(d, 1))
        keep |= {r["id"] for r in rows if datetime.fromisoformat(r["started"]) >= cutoff}
    else:
        seen = set()
        for r in rows:  # newest first -> first hit in a bucket is the newest of that bucket
            t = datetime.fromisoformat(r["started"])
            age_days = (today - t).days
            iso = t.isocalendar()
            for bucket, limit in ((("d", t.date()), d if age_days < d else 0),
                                  (("w", iso[0], iso[1]), w if age_days < w * 7 else 0),
                                  (("m", t.year, t.month), m if age_days < m * 31 else 0)):
                if limit and bucket not in seen:
                    seen.add(bucket); keep.add(r["id"])
    for r in rows:
        if r["id"] not in keep:
            delete_run_files(r, log)
            db.x("UPDATE runs SET deleted=1 WHERE id=?", (r["id"],))
            log(f"حُذفت نسخة قديمة: {Path(r['file']).name}")


def delete_run_files(r, log=print):
    for u in json.loads(r.get("uploads") or "[]"):
        if u.get("status") == "ok":
            d = db.get_item("destinations", u["dest_id"])
            if d:
                try:
                    remove_remote(d, u["path"])
                except Exception as e:  # noqa: BLE001
                    log(f"تعذر حذف النسخة من {u['name']}: {e}")
    if r.get("file"):
        Path(r["file"]).unlink(missing_ok=True)


# ---------------------------------------------------------------- restore
def build_chain(target):
    runs = db.q("SELECT * FROM runs WHERE connection_id=? AND db=? AND status='success' AND deleted=0 "
                "ORDER BY started", (target["connection_id"], target["db"]))
    runs = [r for r in runs if r["file"] and Path(r["file"]).exists()]
    if target["type"] == "full":
        return [target]
    fulls = [r for r in runs if r["type"] == "full" and r["started"] <= target["started"]]
    if not fulls:
        raise RuntimeError("لا توجد نسخة كاملة سابقة لهذه النسخة")
    base = fulls[-1]
    if target["type"] == "diff":
        return [base, target]
    diffs = [r for r in runs if r["type"] == "diff" and base["started"] <= r["started"] <= target["started"]]
    start = diffs[-1] if diffs else base
    logs = [r for r in runs if r["type"] == "log" and start["started"] < r["started"] <= target["started"]]
    return [base] + ([diffs[-1]] if diffs else []) + logs


def start_restore(run_id, new_name, test):
    r = db.q("SELECT * FROM runs WHERE id=?", (run_id,))[0]
    rid = db.x("INSERT INTO runs(schedule_name,connection_id,db,type,trigger,status,started) VALUES(?,?,?,?,?,'running',?)",
               ("اختبار استرجاع" if test else "استرجاع", r["connection_id"], new_name, "restore", "manual", db.now()))
    threading.Thread(target=_restore, args=(rid, r, new_name, test), daemon=True).start()
    return rid


def _restore(rid, target, new_name, test):
    lines = []

    def log(msg):
        lines.append(f"[{datetime.now():%H:%M:%S}] {msg}")
        db.x("UPDATE runs SET log=? WHERE id=?", ("\n".join(lines), rid))

    err, cfg = None, db.get_item("connections", target["connection_id"])
    try:
        if cfg["type"] != "sqlserver":
            raise RuntimeError("الاسترجاع من الواجهة مدعوم لـ SQL Server فقط حاليًا")
        if sql_rows(cfg, f"SELECT DB_ID({ql(new_name)}) AS i")[0]["i"] is not None:
            raise RuntimeError(f"القاعدة {new_name} موجودة مسبقًا - اختر اسمًا جديدًا (لا نكتب فوق القواعد الحالية)")
        chain = build_chain(target)
        log("سلسلة الاسترجاع: " + " ← ".join(f"{c['type']}@{c['started']}" for c in chain))
        info = sql_rows(cfg, "SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS NVARCHAR(500)) AS d, "
                             "CAST(SERVERPROPERTY('InstanceDefaultLogPath') AS NVARCHAR(500)) AS l")[0]
        files = sql_rows(cfg, f"RESTORE FILELISTONLY FROM DISK={ql(chain[0]['file'])}")
        moves = []
        for i, f in enumerate(files):
            isl = f["Type"] == "L"
            folder = info["l"] if isl else info["d"]
            ext = ".ldf" if isl else (".mdf" if i == 0 else ".ndf")
            moves.append(f"MOVE {ql(f['LogicalName'])} TO {ql(os.path.join(folder, f'{new_name}_{i}{ext}'))}")
        for i, c in enumerate(chain):
            last = i == len(chain) - 1
            kind = "LOG" if c["type"] == "log" else "DATABASE"
            opts = ([", ".join(moves)] if i == 0 else []) + ["RECOVERY" if last else "NORECOVERY"]
            log(f"استرجاع {c['type']} - {Path(c['file']).name}")
            sql_exec(cfg, f"RESTORE {kind} {qn(new_name)} FROM DISK={ql(c['file'])} WITH {', '.join(opts)}")
        log("تم الاسترجاع ✔")
        if test:
            try:
                log("فحص سلامة القاعدة المسترجعة (CHECKDB)...")
                sql_exec(cfg, f"DBCC CHECKDB({ql(new_name)}) WITH NO_INFOMSGS")
                log("الفحص ناجح ✔")
            except Exception as e:  # noqa: BLE001 - restore itself succeeded; permission may be missing
                log(f"تعذر تشغيل CHECKDB (الاسترجاع نفسه نجح): {e}")
            finally:
                log("حذف القاعدة التجريبية")
                sql_exec(cfg, f"DROP DATABASE {qn(new_name)}")
    except Exception as e:  # noqa: BLE001
        err = str(e)
        log(f"خطأ: {e}")
    db.x("UPDATE runs SET status=?, finished=?, error=? WHERE id=?",
         ("failed" if err else "success", db.now(), err, rid))
    if err:
        alerts.notify(f"❌ فشل الاسترجاع {new_name}", err, False)
