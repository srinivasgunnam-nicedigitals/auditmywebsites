from fastapi import HTTPException
from sqlalchemy.orm import Session
from models import User
from utils.notifications import send_low_credit_email
import logging

def check_and_deduct_credits(user_id: str, count: int, db: Session):
    """
    Check if user has enough credits and deduct them.
    Raises HTTPException 403 if credits are insufficient.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.credits < count:
        raise HTTPException(
            status_code=403, 
            detail=f"Insufficient credits. You need {count} credits but only have {user.credits}. Please contact support to top up."
        )
        
    user.credits -= count
    
    # Check for low credit notification (threshold = 50)
    low_credit_warning = False
    if user.credits <= 50:
        low_credit_warning = True
        if not user.low_credit_notified:
            logging.info(f"User {user_id} reached {user.credits} credits. Triggering notification.")
            # Trigger email in background optionally, for now sync is fine for small SMTP calls
            sent = send_low_credit_email(user.email, user.credits)
            if sent:
                user.low_credit_notified = True
    
    db.commit()
    db.refresh(user)
    return count, low_credit_warning

def check_user_credits(user_id: int, count: int, db: Session):
    """
    Check if user has enough credits WITHOUT deducting them.
    Raises HTTPException 403 if credits are insufficient.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    if user.credits < count:
        raise HTTPException(
            status_code=403, 
            detail=f"Insufficient credits. You need {count} credits but only have {user.credits}. Please contact support to top up."
        )
    
    low_credit_warning = user.credits <= 50
    return low_credit_warning
