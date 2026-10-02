import models
from database import SessionLocal
import json

def check_results(session_id):
    db = SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session:
            print(f"Session {session_id} not found")
            return
        
        print(f"Session: {session.session_id}")
        print(f"Status: {session.status}")
        print(f"Total Expected: {session.total_expected}")
        print(f"Completed: {session.completed}")
        
        results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        print(f"Results Count: {len(results)}")
        urls_in_db = sorted([r.url for r in results])
        for u in urls_in_db:
            print(f"  {u}")
    finally:
        db.close()

def list_recent_sessions():
    db = SessionLocal()
    try:
        sessions = db.query(models.AuditSession).order_by(models.AuditSession.created_at.desc()).limit(10).all()
        print("Recent Sessions:")
        for s in sessions:
            print(f"  ID: {s.session_id}, Status: {s.status}, Created: {s.created_at}")
    finally:
        db.close()

if __name__ == "__main__":
    check_results("h1_52dbab12")
