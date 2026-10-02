from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from pydantic import BaseModel
from typing import Optional, List
import redis

from database import get_db
import models
from routers.auth import get_current_user_from_cookie
from utils.ui import templates

router = APIRouter(prefix="/admin", tags=["Admin"])

# We'll use the redis instance initialized in main.py, but we can also just create a local client here
# for simplicity if it's running on localhost
try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
    redis_client.ping()
except Exception as e:
    redis_client = None
    print(f"Warning: Redis not available in admin.py: {e}")

class AddCreditsRequest(BaseModel):
    email: str
    credits: int
    description: Optional[str] = "manual top-up"

async def require_admin(admin_user: models.User = Depends(get_current_user_from_cookie)):
    """Dependency to require admin privileges"""
    if not admin_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if not getattr(admin_user, "is_admin", False): # Safely handle if column doesn't exist yet
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return admin_user

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, admin_user: models.User = Depends(require_admin)):
    """Serve the admin dashboard HTML page"""
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "user": admin_user
    })

@router.get("/active-users")
async def get_active_users(
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_admin)
):
    """Get count and list of currently active users"""
    active_users = []
    
    # Try Redis first if configured
    if redis_client:
        try:
            keys = redis_client.keys("active_user:*")
            for key in keys:
                user_id = key.split(":")[1]
                user_info = db.query(models.User).filter(models.User.id == user_id).first()
                if user_info:
                    active_users.append({
                        "user_id": user_id,
                        "username": user_info.username,
                        "email": user_info.email
                    })
                else:
                    active_users.append({"user_id": user_id, "username": "Unknown", "email": "Unknown"})
            
            return {
                "active_users_count": len(active_users),
                "active_users": active_users
            }
        except Exception as e:
            print(f"Redis error when fetching active users: {e}")
            # Fallback to DB below
            
    # Fallback to Database logs if Redis is unavailable or fails
    try:
        from datetime import datetime, timedelta
        five_minutes_ago = datetime.utcnow() - timedelta(minutes=5)
        
        # Get distinct users active in the last 5 minutes
        recent_logs = db.query(models.UserLog.user_id)\
            .filter(models.UserLog.timestamp >= five_minutes_ago)\
            .distinct().all()
            
        for log in recent_logs:
            user_id = log[0]
            user_info = db.query(models.User).filter(models.User.id == user_id).first()
            if user_info:
                active_users.append({
                    "user_id": user_id,
                    "username": user_info.username,
                    "email": user_info.email
                })
            else:
                active_users.append({"user_id": user_id, "username": "Unknown", "email": "Unknown"})
            
        return {
            "active_users_count": len(active_users),
            "active_users": active_users
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch active users: {str(e)}")

@router.get("/logs")
async def get_admin_logs(
    user_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_admin)
):
    """Get paginated and optionally filtered API logs"""
    query = db.query(models.UserLog)
    
    if user_id:
        query = query.filter(models.UserLog.user_id == user_id)
    if endpoint:
        query = query.filter(models.UserLog.endpoint.like(f"%{endpoint}%"))
        
    total = query.count()
    logs = query.order_by(desc(models.UserLog.timestamp)).offset(offset).limit(limit).all()
    
    log_list = [
        {
            "id": log.id,
            "user_id": log.user_id,
            "endpoint": log.endpoint,
            "method": log.method,
            "ip": log.ip_address,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None
        }
        for log in logs
    ]
    
    return {
        "total": total,
        "logs": log_list,
        "limit": limit,
        "offset": offset
    }

@router.post("/add-credits")
async def add_admin_credits(
    request: AddCreditsRequest,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_admin)
):
    """Manually add credits to a user"""
    # Find user
    target_user = db.query(models.User).filter(models.User.email == request.email).first()
    if not target_user:
        raise HTTPException(status_code=404, detail=f"User with email {request.email} not found")
        
    # Update credits
    target_user.credits += request.credits
    
    # Reset notification flag if account balance is restored above threshold
    if target_user.credits > 50:
        target_user.low_credit_notified = False
        
    # Store record
    transaction = models.CreditTransaction(
        user_id=target_user.id,
        amount=request.credits,
        description=request.description
    )
    db.add(transaction)
    db.commit()
    
    return {
        "message": f"Successfully added {request.credits} credits to user {target_user.username}",
        "new_balance": target_user.credits,
        "transaction_id": transaction.id
    }

@router.get("/users")
async def get_all_users(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_admin)
):
    """Get all registered users with their details"""
    query = db.query(models.User)
    total = query.count()
    users = query.order_by(desc(models.User.created_at)).offset(offset).limit(limit).all()
    
    user_list = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "credits": u.credits,
            "is_admin": u.is_admin,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None
        }
        for u in users
    ]
    
    return {
        "total": total,
        "users": user_list,
        "limit": limit,
        "offset": offset
    }

@router.get("/activity-stream")
async def get_activity_stream(
    limit: int = Query(20, ge=1, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    admin_user: models.User = Depends(require_admin)
):
    """Get a stream of recent human-readable activities"""
    activities = []
    
    # 1. Get recent logs that represent "important" actions
    # Map common endpoints to friendly names
    endpoint_map = {
        "/api/auth/login": "logged in",
        "/api/auth/register": "signed up",
        "/api/auth/update-profile": "updated their profile",
        "/api/auth/update-password": "changed their password",
        "/api/auth/reset-password": "requested a password reset",
        "/upload/performance": "started Performance Audit",
        "/upload/accessibility": "started Accessibility Audit",
        "/upload/h1": "started H1 Audit",
        "/upload/phone": "started Phone/CTA Audit",
        "/upload/meta-tags": "started Meta Tags Audit",
        "/upload/image-alt": "started Compare Image Alt Audit",
        "/upload/responsive": "started Responsive Audit",
        "/upload/sitemap": "started Sitemap Audit",
        "/upload/static": "started Static Audit",
        "/upload/dynamic": "started Dynamic Audit",
        "/api/visual-test": "started Visual Comparison Audit",
        "/api/live/search": "used Live Responsive search",
        "/admin/add-credits": "was granted credits by admin",
        "/api/sessions": "cleared their history"
    }
    
    recent_logs = db.query(models.UserLog, models.User.email, models.User.username, models.User.credits)\
        .join(models.User, models.UserLog.user_id == models.User.id)\
        .filter(or_(models.UserLog.method == "POST", models.UserLog.method == "DELETE"))\
        .order_by(desc(models.UserLog.timestamp))\
        .offset(offset)\
        .limit(limit * 2).all() # Fetch more to filter out uninteresting ones
        
    for log, email, username, credits in recent_logs:
        action = None
        for path, desc_text in endpoint_map.items():
            if log.endpoint.startswith(path):
                action = desc_text
                break
        
        if not action:
            continue # Skip uninteresting logs (default GETs, etc.)
        
        activities.append({
            "id": f"log_{log.id}",
            "user": username,
            "email": email,
            "action": action,
            "type": "log",
            "credits_used": log.credits_used,
            "credits_pending": log.credits_balance if log.credits_balance is not None else credits,
            "timestamp": log.timestamp.isoformat()
        })
        
    # 2. Get recently completed sessions
    recent_sessions = db.query(models.AuditSession, models.User.email, models.User.username, models.User.credits)\
        .join(models.User, models.AuditSession.user_id == models.User.id)\
        .filter(models.AuditSession.status == "completed")\
        .order_by(desc(models.AuditSession.completed_at))\
        .offset(offset)\
        .limit(10).all()
        
    for session, email, username, credits in recent_sessions:
        activities.append({
            "id": f"session_{session.id}",
            "user": username,
            "email": email,
            "action": f"finished {session.session_type.capitalize()} Audit: {session.name}",
            "type": "session",
            "credits_used": session.credits_used,
            "credits_pending": session.credits_balance if session.credits_balance is not None else credits,
            "timestamp": session.completed_at.isoformat() if session.completed_at else session.created_at.isoformat()
        })
        
    # Sort everything by timestamp and limit
    activities.sort(key=lambda x: x["timestamp"], reverse=True)
    return activities[:limit]
