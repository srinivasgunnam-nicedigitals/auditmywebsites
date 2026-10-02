import sqlite3
import os

def migrate():
    db_path = "database/sitetoolpro.db"
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}. Skipping migration (it will be created fresh).")
        return

    conn = sqlite3.connect(db_path, timeout=30)
    cursor = conn.cursor()

    print(f"Starting migration on {db_path}...")

    # 1. Add columns to 'users' table
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
        print("Added 'is_admin' to 'users'")
    except sqlite3.OperationalError:
        print("'is_admin' already exists or users table missing")

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN low_credit_notified BOOLEAN DEFAULT 0")
        print("Added 'low_credit_notified' to 'users'")
    except sqlite3.OperationalError:
        print("'low_credit_notified' already exists")

    # 2. Add 'credits_used' to 'user_logs'
    try:
        cursor.execute("ALTER TABLE user_logs ADD COLUMN credits_used INTEGER DEFAULT 0")
        print("Added 'credits_used' to 'user_logs'")
    except sqlite3.OperationalError:
        print("'credits_used' already exists or user_logs table missing")

    try:
        cursor.execute("ALTER TABLE audit_sessions ADD COLUMN credits_used INTEGER DEFAULT 0")
        print("Added 'credits_used' to 'audit_sessions'")
    except sqlite3.OperationalError:
        print("'credits_used' already exists or audit_sessions table missing")

    # 4. Add 'credits_balance' to 'user_logs' and 'audit_sessions'
    try:
        cursor.execute("ALTER TABLE user_logs ADD COLUMN credits_balance INTEGER")
        print("Added 'credits_balance' to 'user_logs'")
    except sqlite3.OperationalError:
        print("'credits_balance' already exists in 'user_logs'")

    try:
        cursor.execute("ALTER TABLE audit_sessions ADD COLUMN credits_balance INTEGER")
        print("Added 'credits_balance' to 'audit_sessions'")
    except sqlite3.OperationalError:
        print("'credits_balance' already exists in 'audit_sessions'")

    # 5. Create new tables if they don't exist
    # User Logs (if somehow missing)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_logs (
        id INTEGER PRIMARY KEY,
        user_id VARCHAR,
        endpoint VARCHAR,
        method VARCHAR,
        ip_address VARCHAR,
        credits_used INTEGER DEFAULT 0,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Credit Transactions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS credit_transactions (
        id INTEGER PRIMARY KEY,
        user_id VARCHAR,
        amount INTEGER,
        description VARCHAR,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()
    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()