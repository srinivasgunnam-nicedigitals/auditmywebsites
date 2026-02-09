from sqlalchemy import inspect, text
from database import engine

def migrate():
    try:
        with engine.connect() as conn:
            inspector = inspect(engine)
            columns = [col['name'] for col in inspector.get_columns('audit_sessions')]
            
            if 'browsers' not in columns:
                print("Adding 'browsers' column...")
                conn.execute(text("ALTER TABLE audit_sessions ADD COLUMN browsers TEXT DEFAULT '[]'"))
                conn.commit()
                
            if 'resolutions' not in columns:
                print("Adding 'resolutions' column...")
                conn.execute(text("ALTER TABLE audit_sessions ADD COLUMN resolutions TEXT DEFAULT '[]'"))
                conn.commit()
                
            print("Migration successful!")
    except Exception as e:
        print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
