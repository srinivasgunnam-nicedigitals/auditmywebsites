from database import SessionLocal
from models import AuditSession

db = SessionLocal()
sessions = db.query(AuditSession).all()

print(f"Total sessions: {len(sessions)}")
for s in sessions:
    if s.session_id == 'undefined' or s.session_id is None or s.session_id == 'None':
        print(f"Found invalid session: ID={s.session_id}, Type={s.session_type}, Status={s.status}")

# Also check for any session that might be causing issues
print("\nListing all sessions:")
for s in sessions:
    print(f"ID: {s.session_id}, Type: {s.session_type}, Status: {s.status}")

db.close()
