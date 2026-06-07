#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sqlite3
from config.settings import DB_PATH
from core.database import init_db

# Initialize database
init_db()

# Check tables
print(f"Database path: {DB_PATH}")
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in c.fetchall()]
print(f"Tables: {tables}")

# Check logs table structure
if 'logs' in tables:
    c.execute("PRAGMA table_info(logs)")
    columns = c.fetchall()
    print("\nLogs table columns:")
    for col in columns:
        print(f"  {col[1]}: {col[2]}")
    
    # Check recent logs
    c.execute("SELECT COUNT(*) FROM logs")
    count = c.fetchone()[0]
    print(f"\nTotal logs: {count}")
    
    if count > 0:
        c.execute("SELECT printer_ip, type, message, paper_size FROM logs ORDER BY timestamp DESC LIMIT 3")
        for row in c.fetchall():
            print(f"\nIP: {row[0]}")
            print(f"Type: {row[1]}")
            print(f"Message: {row[2][:60] if row[2] else None}")
            print(f"Paper Size: {row[3]}")

conn.close()
