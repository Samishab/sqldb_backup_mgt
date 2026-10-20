"""Creates a small demo SQLite database to try the panel without SQL Server."""
import sqlite3, random
c = sqlite3.connect("data/demo.db")
c.execute("CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, customer TEXT, amount REAL)")
c.executemany("INSERT INTO orders(customer,amount) VALUES(?,?)", [(f"cust{i}", random.random()*100) for i in range(50000)])
c.commit(); print("data/demo.db ready")
