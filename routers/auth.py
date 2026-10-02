from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import timedelta, datetime
import uuid
import os

from database import get_db
import models
import auth
from config import settings
from utils.ui import templates
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

router = APIRouter()

# Pydantic models for JSON requests
class LoginRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class RegisterRequest(BaseModel):
    email: str
    password: str
    username: Optional[str] = None

class GoogleLoginRequest(BaseModel):
    token: str

class PasswordUpdateRequest(BaseModel):
    current_password: str
    new_password: str

class ProfileUpdateRequest(BaseModel):
    username: str
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

# ========== AUTHENTICATION DEPENDENCIES ==========

async def get_current_user_from_cookie(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        user_id = auth.verify_token(token)
        if not user_id:
            return None
        return db.query(models.User).filter(models.User.id == user_id).first()
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

async def require_auth(request: Request, db: Session = Depends(get_db)):
    """Dependency to require authentication for protected routes."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    return user

# ========== AUTH ROUTES ==========

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    """Login page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("login.html", {
        "request": request, 
        "google_client_id": settings.google_client_id
    })

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    """Register page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("register.html", {
        "request": request,
        "google_client_id": settings.google_client_id
    })

@router.post("/api/auth/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    try:
        # Generate username if not provided
        username = request.username
        if not username:
            email_part = request.email.split('@')[0]
            # Clean email part to be a valid username
            import re
            base_username = re.sub(r'[^a-zA-Z0-9_]', '', email_part)
            if not base_username:
                base_username = "user"
            
            username = base_username
            counter = 1
            while db.query(models.User).filter(models.User.username == username).first():
                username = f"{base_username}_{counter}"
                counter += 1

        user = auth.register_user(request.email, request.password, username, db)
        # Create Token
        access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = auth.create_access_token(
            data={"sub": user.id}, expires_delta=access_token_expires
        )
        
        resp = JSONResponse({
            "access_token": access_token, 
            "token_type": "bearer", 
            "user": {"id": user.id, "username": user.username, "email": user.email}
        })
        resp.set_cookie(
            key="access_token", 
            value=access_token, 
            httponly=True, 
            max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            path="/"
        )
        return resp
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Registration Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/auth/login")
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    try:
        # Check if username is email
        user = None
        if "@" in request.username:
             user = db.query(models.User).filter(models.User.email == request.username).first()
        
        if not user:
            user = db.query(models.User).filter(models.User.username == request.username).first()
            
        if not user or not auth.verify_password(request.password, user.hashed_password):
            raise HTTPException(status_code=400, detail="Invalid credentials")
            
        # Create Token
        access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = auth.create_access_token(
            data={"sub": user.id}, expires_delta=access_token_expires
        )
        
        resp = JSONResponse({
            "access_token": access_token, 
            "token_type": "bearer", 
            "user": {"id": user.id, "username": user.username, "email": user.email}
        })
        resp.set_cookie(
            key="access_token", 
            value=access_token, 
            httponly=True, 
            max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            path="/"
        )
        return resp
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Login Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/auth/google")
async def google_login(request: GoogleLoginRequest, db: Session = Depends(get_db)):
    try:
        id_info = id_token.verify_oauth2_token(
            request.token, 
            google_requests.Request(), 
            settings.google_client_id,
            clock_skew_in_seconds=10
        )

        email = id_info.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Google token does not contain email")
        
        user = db.query(models.User).filter(models.User.email == email).first()
        
        if not user:
            username = email.split("@")[0]
            base_username = username
            counter = 1
            while db.query(models.User).filter(models.User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1
                
            random_password = auth.get_password_hash(uuid.uuid4().hex)
            
            user = models.User(
                id=str(uuid.uuid4()),
                email=email,
                username=username,
                hashed_password=random_password,
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            
        access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = auth.create_access_token(
            data={"sub": user.id, "auth_provider": "google"}, expires_delta=access_token_expires
        )
        
        resp = JSONResponse({"access_token": access_token, "token_type": "bearer", "redirect_url": "/platform/dashboard"})
        resp.set_cookie(
            key="access_token", 
            value=access_token, 
            httponly=True, 
            max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax",
            path="/"
        )
        return resp
    except Exception as e:
        print(f"Google Auth Error: {e}")
        raise HTTPException(status_code=401, detail=str(e))

@router.get("/api/auth/status")
async def auth_status(user: models.User = Depends(get_current_user_from_cookie)):
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"id": user.id, "username": user.username, "email": user.email}

@router.get("/logout")
async def logout_get():
    """Logout user and redirect to login page"""
    response = RedirectResponse(url="/?signin=true", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token", path="/")
    return response

@router.post("/api/auth/logout")
async def logout_post():
    """Logout user and redirect to login page"""
    response = RedirectResponse(url="/?signin=true", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="access_token", path="/")
    return response

@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request):
    return templates.TemplateResponse("reset-password.html", {"request": request})

@router.get("/forgot-password")
async def forgot_password_redirect():
    return RedirectResponse(url="/reset-password")

@router.post("/api/auth/update-password")
async def update_password(
    request: PasswordUpdateRequest,
    user: models.User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    if request.current_password == request.new_password:
        raise HTTPException(status_code=400, detail="you are using same password please enter a new one")

    if not auth.verify_password(request.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid current password")
    
    user.hashed_password = auth.get_password_hash(request.new_password)
    db.commit()
    return {"message": "Password updated successfully"}

@router.post("/api/auth/update-profile")
async def update_profile(
    request: ProfileUpdateRequest,
    user: models.User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    existing_user = db.query(models.User).filter(models.User.username == request.username).first()
    if existing_user and existing_user.id != user.id:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    existing_email = db.query(models.User).filter(models.User.email == request.email).first()
    if existing_email and existing_email.id != user.id:
        raise HTTPException(status_code=400, detail="Email already registered")

    user.username = request.username
    user.email = request.email
    db.commit()
    return {"message": "Profile updated successfully", "username": user.username, "email": user.email}

@router.post("/api/auth/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Reset user password with valid token"""
    # Validate token
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == request.token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Validate password
    if len(request.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    # Get user
    user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    user.hashed_password = auth.get_password_hash(request.password)
    reset_token.used = True
    db.commit()
    
    return {"message": "Password reset successful"}
