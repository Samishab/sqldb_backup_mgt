"""Inserts rows into DemoShop every few seconds so differential/log backups have changes. Ctrl+C to stop."""
import time
from app import engine
SRV = {"type": "sqlserver", "server": r"localhost\SQLEXPRESS", "auth": "windows"}
while True:
    engine.sql_exec(SRV, "USE DemoShop; INSERT INTO orders(customer,amount) SELECT TOP 2000 'c'+CAST(ABS(CHECKSUM(NEWID()))%1000 AS VARCHAR), ABS(CHECKSUM(NEWID()))%10000/100.0 FROM sys.all_objects a, sys.all_objects b")
    print("inserted 2000 rows"); time.sleep(10)
