from database import SessionLocal
import models
import json

session_id = "phn_c5c71bd8"
db = SessionLocal()
session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
if session:
    print(f"Session ID: {session.session_id}")
    print(f"Status: {session.status}")
    print(f"Completed: {session.completed}")
    print(f"Total: {session.total_expected}")
    
    results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
    print(f"Results Count: {len(results)}")
    for r in results[:5]:
        print(f" - URL: {r.url}, Phone Count: {r.phone_count}")
else:
    print("Session not found")
db.close()
