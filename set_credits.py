from database import SessionLocal
from models import User
import sys

def set_user_credits(email, amount):
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.credits = amount
        user.low_credit_notified = False # Reset notification flag for testing
        db.commit()
        print(f"Successfully set credits for {email} to {amount}")
    else:
        print(f"User {email} not found")
    db.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python set_credits.py <email> <amount>")
    else:
        set_user_credits(sys.argv[1], int(sys.argv[2]))
