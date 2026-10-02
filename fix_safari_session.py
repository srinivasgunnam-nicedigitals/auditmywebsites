from database import SessionLocal
from models import StaticAuditResult, AuditSession
import json

db = SessionLocal()
session_id = "3062cccc-aa12-42b4-81c5-27be4726f70e"

print(f"Fixing session {session_id}...")

# 1. Update Results
results = db.query(StaticAuditResult).filter_by(session_id=session_id).all()
count = 0
for r in results:
    if r.browser == "safari":
        r.browser = "Safari"
        count += 1

print(f"Updated {count} result records to 'Safari'")

# 2. Update Session Config (if needed)
session = db.query(AuditSession).filter_by(session_id=session_id).first()
if session:
    try:
        browsers = json.loads(session.browsers)
        if "safari" in browsers:
            browsers = ["Safari" if b == "safari" else b for b in browsers]
            session.browsers = json.dumps(browsers)
            print("Updated session configuration browsers list")
    except:
        print("Could not parse session browsers JSON")

db.commit()
print("Done.")
