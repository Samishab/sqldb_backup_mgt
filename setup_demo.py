"""Seeds a demo SQL Server database (DemoShop) + connection + destination + fast demo schedules.
Run once:  .venv\Scripts\python setup_demo.py     (the panel asks for a password on first visit)"""
import sys
from app import db, engine
SRV = {"type": "sqlserver", "server": r"localhost\SQLEXPRESS", "auth": "windows"}
engine.sql_exec(SRV, "IF DB_ID('DemoShop') IS NULL CREATE DATABASE DemoShop")
engine.sql_exec(SRV, "ALTER DATABASE DemoShop SET RECOVERY FULL")
engine.sql_exec(SRV, "USE DemoShop; IF OBJECT_ID('orders') IS NULL CREATE TABLE orders(id INT IDENTITY PRIMARY KEY, customer NVARCHAR(50), amount DECIMAL(10,2), note CHAR(200) DEFAULT 'x')")
db.init()
if not db.list_items("connections"):
    cid = db.save_item("connections", None, {"name": "SQL Express المحلي", **SRV})
    did = db.save_item("destinations", None, {"name": "نسخة ثانية (مجلد)", "type": "local", "path": str(db.DATA / "copy"), "enabled": True})
    base = dict(connection_id=cid, databases=["DemoShop"], destinations=[did], verify=True, enabled=True)
    db.save_item("schedules", None, {"name": "Full كل 10 دقائق (تجريبي)", "type": "full", "trigger": {"mode": "interval", "every": 10, "unit": "minutes"}, "retention": {"daily": 1, "weekly": 0, "monthly": 0}, **base})
    db.save_item("schedules", None, {"name": "Differential كل 4 دقائق (تجريبي)", "type": "diff", "trigger": {"mode": "interval", "every": 4, "unit": "minutes"}, "retention": {"daily": 1, "weekly": 0, "monthly": 0}, **base})
    db.save_item("schedules", None, {"name": "Log كل دقيقتين (تجريبي)", "type": "log", "trigger": {"mode": "interval", "every": 2, "unit": "minutes"}, "retention": {"daily": 1, "weekly": 0, "monthly": 0}, **base})
print("demo ready")
