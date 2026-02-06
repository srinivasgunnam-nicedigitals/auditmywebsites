from database import SessionLocal
from models import StaticAuditResult, AuditSession
import json

db = SessionLocal()

print("=== STATIC AUDIT RESULTS ===")
results = db.query(StaticAuditResult).all()
for r in results:
    print(f"ID: {r.id} | Session: {r.session_id} | Browser: {r.browser} | URL: {r.url}")
    print(f"  Path: {r.screenshot_path}")
    print(f"  Filename: {r.filename}")
    print("-" * 50)

print("\n=== AUDIT SESSIONS (STATIC) ===")
sessions = db.query(AuditSession).filter(AuditSession.session_type == "static").all()
for s in sessions:
    print(f"Session: {s.session_id} | Status: {s.status}")
    print(f"  Browsers: {s.browsers}")
    print("-" * 50)
