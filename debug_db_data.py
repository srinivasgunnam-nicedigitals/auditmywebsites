
from sqlalchemy.orm import Session
from database import SessionLocal, engine
import models
from sqlalchemy import func

def debug_data():
    db = SessionLocal()
    try:
        print("=== USERS ===")
        users = db.query(models.User).all()
        for u in users:
            print(f"User: {u.username} (ID: {u.id}, Type: {type(u.id)})")

        print("\n=== AUDIT SESSIONS (First 20) ===")
        sessions = db.query(models.AuditSession).limit(20).all()
        for s in sessions:
            print(f"Session: {s.session_id} | UserID: {s.user_id} (Type: {type(s.user_id)})")

        print("\n=== STATS CALCULATION DEBUG ===")
        for u in users:
            count_sql = db.query(models.AuditSession).filter(models.AuditSession.user_id == u.id).count()
            print(f"User {u.username} SQL Count: {count_sql}")
            
            # Python side check
            # all_sessions = db.query(models.AuditSession).all()
            # py_count = sum(1 for s in all_sessions if str(s.user_id) == str(u.id))
            # print(f"User {u.username} Python Count: {py_count}")

        print("\n=== TOTAL AUDITS IN DB ===")
        total = db.query(models.AuditSession).count()
        print(f"Total: {total}")

    finally:
        db.close()

if __name__ == "__main__":
    debug_data()
