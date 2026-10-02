import sqlite3
import os

db_path = os.path.join("database", "sitetoolpro.db")

def migrate():
    print(f"Connecting to database at {db_path}...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if the column already exists
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "is_admin" not in columns:
            print("Adding 'is_admin' column to 'users' table...")
            cursor.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            conn.commit()
            print("Column 'is_admin' added successfully.")
        else:
            print("Column 'is_admin' already exists.")
            
        conn.close()
    except Exception as e:
        print(f"Migration error: {e}")

if __name__ == "__main__":
    migrate()
