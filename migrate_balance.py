import sqlite3
import os

db_path = "./database/sitetoolpro.db"

if not os.path.exists(db_path):
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("Adding credits_balance to user_logs...")
try:
    cursor.execute("ALTER TABLE user_logs ADD COLUMN credits_balance INTEGER;")
    print("Success: Added credits_balance to user_logs")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("Column credits_balance already exists in user_logs")
    else:
        print(f"Error adding column to user_logs: {e}")

print("Adding credits_balance to audit_sessions...")
try:
    cursor.execute("ALTER TABLE audit_sessions ADD COLUMN credits_balance INTEGER;")
    print("Success: Added credits_balance to audit_sessions")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("Column credits_balance already exists in audit_sessions")
    else:
        print(f"Error adding column to audit_sessions: {e}")

conn.commit()
conn.close()
print("Migration completed.")
