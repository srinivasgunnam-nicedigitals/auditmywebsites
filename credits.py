
import sys
import os
# Ensure the current directory is in the path so we can import models and database
sys.path.append(os.getcwd())

from database import SessionLocal
import models

def add_unlimited_credits(email: str, amount: int = 999999999):
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            user.credits = amount
            db.commit()
            print(f"Successfully updated credits for {email} to {amount}")
        else:
            print(f"User with email {email} not found")
    except Exception as e:
        print(f"Error for {email}: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    emails = ["akashniceinteractive@gmail.com"]
    for email in emails:
        add_unlimited_credits(email)