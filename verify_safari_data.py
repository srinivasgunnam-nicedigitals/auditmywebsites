from database import SessionLocal
from models import StaticAuditResult, AuditSession
import sys

# Set encoding to utf-8 for console output
sys.stdout.reconfigure(encoding='utf-8')

db = SessionLocal()

session_id = "3062cccc-aa12-42b4-81c5-27be4726f70e"
print(f"Checking Session: {session_id}")

results = db.query(StaticAuditResult).filter_by(session_id=session_id).all()
print(f"Total Results: {len(results)}")

for r in results:
    print(f"ID: {r.id}")
    print(f"Browser (Raw): '{r.browser}'")
    print(f"Browser (Repr): {repr(r.browser)}")
    print(f"URL: {r.url}")
    print("-" * 20)

print("\nSession Details:")
session = db.query(AuditSession).filter_by(session_id=session_id).first()
if session:
    print(f"Session Browsers JSON: {session.browsers}")
else:
    print("Session not found")
