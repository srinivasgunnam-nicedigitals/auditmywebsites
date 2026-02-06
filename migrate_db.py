import sqlite3

def migrate():
    try:
        conn = sqlite3.connect('sitetoolpro.db')
        cursor = conn.cursor()
        
        # Check existing columns
        cursor.execute("PRAGMA table_info(audit_sessions)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'browsers' not in columns:
            print("Adding 'browsers' column...")
            cursor.execute("ALTER TABLE audit_sessions ADD COLUMN browsers TEXT DEFAULT '[]'")
            
        if 'resolutions' not in columns:
            print("Adding 'resolutions' column...")
            cursor.execute("ALTER TABLE audit_sessions ADD COLUMN resolutions TEXT DEFAULT '[]'")
            
        conn.commit()
        print("Migration successful!")
    except Exception as e:
        print(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
