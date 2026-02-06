import os
import sys
import asyncio

# Fix for Windows asyncio loop - Playwright requires ProactorEventLoop for subprocess support
# This must be set before uvicorn starts the loop or as early as possible during import
if sys.platform.startswith("win"):
    print("[SYSTEM] Setting WindowsProactorEventLoopPolicy...", flush=True)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# main.py — COMPLETE UPDATED VERSION WITH ALL FEATURES

import re
import urllib.parse
from bs4 import BeautifulSoup
import json
import csv
import io
import random
import shutil
import hashlib
from typing import List, Tuple, Dict, Optional
from datetime import datetime, timedelta

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, Form, Request, Depends, HTTPException, status, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.requests import Request as StarletteRequest # Renamed to avoid conflict with fastapi.Request
from starlette.datastructures import UploadFile as StarletteUploadFile # Renamed to avoid conflict with fastapi.UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile # Renamed to avoid conflict with fastapi.UploadFile
import uuid
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from utils import dom_diff
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from pydantic import BaseModel

from PIL import Image, ImageDraw, ImageFont
import imageio
import numpy as np
from playwright.async_api import async_playwright
import phonenumbers
from phonenumbers import PhoneNumberMatcher, PhoneNumberFormat, is_valid_number, format_number
import concurrent.futures
import functools
import httpx # Added for proxy

# Create a process pool for heavy CPU/IO tasks
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# Import database and models
import database
import models
import auth
from config import settings
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from dotenv import load_dotenv

load_dotenv()

# Create necessary directories
os.makedirs("screenshots", exist_ok=True)
os.makedirs("videos", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("temp_frames", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("diffs", exist_ok=True)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "558208377801-9tshv1q3kpq66iphi7ihp443n8dvfons.apps.googleusercontent.com")

app = FastAPI()

# Middleware to handle .html redirects for legacy UI links


@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Serve the public landing page"""
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "google_client_id": GOOGLE_CLIENT_ID
    })

@app.middleware("http")
async def redirect_html_extension(request: Request, call_next):
    path = request.url.path
    if path.endswith(".html"):
        new_path = path[:-5]
        # Some special mappings if needed
        if "device_lab" in new_path: new_path = "/platform/device-lab"
        if "audit_history" in new_path: new_path = "/platform/history"
        if "performance_audit" in new_path: new_path = "/platform/performance"
        if "accessibility_audit" in new_path: new_path = "/platform/accessibility"
        if "phone_validator" in new_path: new_path = "/phone-audit"
        if "h1_tags" in new_path: new_path = "/h1-audit"
        if "metatags" in new_path: new_path = "/scan/meta-tags"
        if "sitemaps" in new_path: new_path = "/scan/xml-sitemaps"

        # if "index" in new_path: new_path = "/platform/dashboard" # REMOVED: index.html should go to root or login, but dashboard is now a dynamic route
        
        return RedirectResponse(url=new_path, status_code=301)
    return await call_next(request)



# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
app.mount("/videos", StaticFiles(directory="videos"), name="videos")

# Favicon route
@app.get("/favicon.ico")
async def favicon():
    """Serve favicon"""
    from fastapi.responses import FileResponse
    import os
    favicon_path = "static/favicon.png"
    if os.path.exists(favicon_path):
        return FileResponse(favicon_path)
    return Response(status_code=404)
app.mount("/diffs", StaticFiles(directory="diffs"), name="diffs")

templates = Jinja2Templates(directory="templates")

# ========== CUSTOM JINJA2 FILTERS ==========

def from_json(value):
    """Custom Jinja2 filter to parse JSON strings"""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return []
    return value

# Add custom filters to Jinja2 environment
templates.env.filters['from_json'] = from_json

def to_json(value):
    """Custom Jinja2 filter to convert to JSON string"""
    return json.dumps(value)

templates.env.filters['to_json'] = to_json
# ===========================================

# Create database tables
models.Base.metadata.create_all(bind=database.engine)

# Global dictionary to track running tasks
running_tasks = {}

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount audit result folders
os.makedirs("screenshots", exist_ok=True)
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")

os.makedirs("videos", exist_ok=True)
app.mount("/videos", StaticFiles(directory="videos"), name="videos")

os.makedirs("h1-audits", exist_ok=True)
app.mount("/h1-audits", StaticFiles(directory="h1-audits"), name="h1-audits")

os.makedirs("phone-audits", exist_ok=True)
app.mount("/phone-audits", StaticFiles(directory="phone-audits"), name="phone-audits")

# Pydantic models for JSON requests
class LoginRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str

class GoogleLoginRequest(BaseModel):
    token: str

class PasswordUpdateRequest(BaseModel):
    current_password: str
    new_password: str

# ========== AUTHENTICATION MIDDLEWARE ==========

async def get_current_user_from_cookie(request: Request, db: Session = Depends(auth.get_db)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        # Use the verify_token function from auth.py
        user_id = auth.verify_token(token)
        if not user_id:
            return None
        
        # Get user from database - ID is now String (UUID)
        user = db.query(models.User).filter(models.User.id == user_id).first()
        return user
    except Exception as e:
        print(f"Authentication error: {e}")
        return None

# ========== AUTHENTICATION DEPENDENCY ==========

async def require_auth(request: Request, db: Session = Depends(auth.get_db)):
    """Dependency to require authentication for protected routes."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    
    # Enable RLS for this request - REMOVED for SQLite
    # auth.set_db_session_user(db, user.id)
    
    return user

    return user

# ========== GOOGLE AUTH ROUTE ==========

@app.post("/api/auth/google")
async def google_login(request: GoogleLoginRequest, db: Session = Depends(auth.get_db), response: Response = None):
    try:
        # Verify the token
        id_info = id_token.verify_oauth2_token(
            request.token, 
            google_requests.Request(), 
            GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10
        )

        email = id_info.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Google token does not contain email")
        
        # Check if user exists
        user = db.query(models.User).filter(models.User.email == email).first()
        
        if not user:
            # Create new user
            username = email.split("@")[0]
            # Ensure unique username
            base_username = username
            counter = 1
            while db.query(models.User).filter(models.User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1
                
            # Random password (they should use Google to login, or reset password later)
            random_password = auth.get_password_hash(uuid.uuid4().hex)
            
            user = models.User(
                id=str(uuid.uuid4()),  # Explicitly generate UUID
                email=email,
                username=username,
                hashed_password=random_password,
                is_active=True
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            
        # Create JWT token
        access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = auth.create_access_token(
            data={"sub": user.id}, expires_delta=access_token_expires
        )
        
        # Determine redirect (simulated for now, frontend handles it)
        redirect_url = "/platform/dashboard"
        
        # Set cookie if response object provided (though usually returned as JSON)
        # We return JSON, frontend will set cookie or we rely on JS? 
        # Better to return JSON and let frontend redirect.
        # BUT, to be safe, we can set cookie via response
        resp = JSONResponse({"access_token": access_token, "token_type": "bearer", "redirect_url": redirect_url})
        resp.set_cookie(
            key="access_token", 
            value=access_token, 
            httponly=True, 
            max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax"
        )
        
        return resp

    except ValueError as e:
        # Invalid token - Log the specific error
        print(f"Google Token Verification Error: {e}")
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")
    except Exception as e:
        print(f"Google Auth Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/update-password")
async def update_password(
    request: PasswordUpdateRequest,
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    if request.current_password == request.new_password:
        raise HTTPException(status_code=400, detail="you are using same password please enter a new one")

    if not auth.verify_password(request.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Invalid current password")
    
    user.hashed_password = auth.get_password_hash(request.new_password)
    db.commit()
    
    return {"message": "Password updated successfully"}

class ProfileUpdateRequest(BaseModel):
    username: str
    email: str

@app.post("/api/auth/update-profile")
async def update_profile(
    request: ProfileUpdateRequest,
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    # Check if username exists and belongs to another user
    existing_user = db.query(models.User).filter(models.User.username == request.username).first()
    if existing_user and existing_user.id != user.id:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    # Check if email exists and belongs to another user
    existing_email = db.query(models.User).filter(models.User.email == request.email).first()
    if existing_email and existing_email.id != user.id:
        raise HTTPException(status_code=400, detail="Email already registered")

    user.username = request.username
    user.email = request.email
    db.commit()
    
    return {"message": "Profile updated successfully", "username": user.username, "email": user.email}

def get_unique_filename(url: str) -> str:
    """Generate unique filename using last path segment + domain"""
    parsed = urllib.parse.urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    domain = re.sub(r'[^\w\.-]', '-', domain)
    
    path = parsed.path.strip("/")
    if not path or path in ("", "/"):
        page_name = "home"
    else:
        segments = [s for s in path.split("/") if s]
        if segments:
            page_name = segments[-1].split('.')[0]
            page_name = re.sub(r'[^\w\-]', '-', page_name).strip("-").lower()
            if not page_name or page_name in ("index", "home"):
                page_name = "home"
            if len(page_name) > 50:
                page_name = page_name[:47] + "..."
        else:
            page_name = "home"
    
    return f"{page_name}__{domain}"

# ========== STATIC AUDIT FUNCTIONS ==========

# ========== STATIC AUDIT FUNCTIONS ==========

async def capture_screenshots(urls: List[str], browsers: List[str], resolutions: List[Tuple[int, int]], session_id: str, user_id: int, db: Session, access_token: str = None):
    session_folder = f"screenshots/{session_id}"
    os.makedirs(session_folder, exist_ok=True)
    
    display_url_prefix = "/screenshots"
    config = { # This config dictionary was misplaced in the original code, moving it here.
        "urls": urls,
        "browsers": browsers,
        "resolutions": [f"{w}x{h}" for w, h in resolutions],
        "type": "static"
    }
    with open(f"{session_folder}/config.json", "w") as f:
        json.dump(config, f)

    try:
        async with async_playwright() as p:
            browser_map = {
                "Chrome": p.chromium,
                "Edge": p.chromium,
                "Firefox": p.firefox,
                "Safari": p.webkit,
                "chrome": p.chromium,
                "chromium": p.chromium,
                "edge": p.chromium,
                "firefox": p.firefox,
                "safari": p.webkit
            }

            # AGGRESSIVE OPTIMIZATION: 5 URLs in parallel
            sem = asyncio.Semaphore(5)

            async def process_url(page, url, w, h, browser_name):
                unique = get_unique_filename(url)
                
                # Check if task was stopped - expire cache to get fresh status
                db.expire_all()  # Force SQLAlchemy to fetch fresh data
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if session and session.status == "stopped":
                    print(f"[STOP] Detected stopped status for session {session_id}, terminating...")
                    return

                try:
                    await page.set_viewport_size({"width": w, "height": h})
                    
                    # Enhanced Safari navigation with comprehensive error handling
                    navigation_success = False
                    max_navigation_attempts = 3
                    
                    for attempt in range(max_navigation_attempts):
                        try:
                            print(f"[DEBUG] Safari navigation attempt {attempt + 1} for {url}")
                            
                            # Try different navigation strategies
                            if attempt == 0:
                                # First attempt: Standard approach
                                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                            elif attempt == 1:
                                # Second attempt: Faster loading
                                await page.goto(url, wait_until="commit", timeout=20000)
                            else:
                                # Final attempt: Minimal waiting
                                await page.goto(url, wait_until="load", timeout=15000)
                            
                            # Wait for page stabilization
                            await page.wait_for_timeout(2000)
                            
                            # Verify page loaded successfully
                            current_url = page.url
                            page_title = await page.title()
                            
                            print(f"[DEBUG] Safari navigation successful - URL: {current_url}, Title: {page_title}")
                            
                            # Check for error conditions
                            if current_url != "about:blank" and "error" not in current_url.lower():
                                navigation_success = True
                                break
                            else:
                                print(f"[DEBUG] Safari got invalid page (attempt {attempt + 1}): {current_url}")
                                
                        except Exception as nav_error:
                            print(f"[DEBUG] Safari navigation attempt {attempt + 1} failed: {nav_error}")
                            if attempt < max_navigation_attempts - 1:
                                await page.wait_for_timeout(1000)  # Brief pause between attempts
                                continue
                            else:
                                # All navigation attempts failed
                                raise nav_error
                    
                    if not navigation_success:
                        raise Exception("All Safari navigation attempts failed")
                    
                    # Wait for network stabilization
                    try:
                        await page.wait_for_load_state("networkidle", timeout=10000)
                    except:
                        print(f"[DEBUG] Network idle timeout for {url}, proceeding with content loaded")
                    
                except Exception as e:
                    print(f"[ERROR] Safari navigation completely failed for {url}: {e}")
                    # Create detailed error placeholder
                    # from PIL import Image, ImageDraw, ImageFont
                    error_path = f"{session_folder}/{browser_name}/{unique}__{w}x{h}_nav_error.png"
                    
                    try:
                        placeholder = Image.new('RGB', (1200, 800), color=(25, 25, 35))
                        draw = ImageDraw.Draw(placeholder)
                        
                        # Try to get fonts
                        try:
                            font_large = ImageFont.truetype("arial.ttf", 28)
                            font_medium = ImageFont.truetype("arial.ttf", 20)
                            font_small = ImageFont.truetype("arial.ttf", 16)
                        except:
                            font_large = ImageFont.load_default()
                            font_medium = ImageFont.load_default()
                            font_small = ImageFont.load_default()
                        
                        # Draw error information
                        draw.text((50, 50), "Safari Navigation Error", fill=(220, 100, 100), font=font_large)
                        draw.text((50, 100), f"URL: {url}", fill=(180, 180, 200), font=font_medium)
                        draw.text((50, 140), f"Error: {str(e)[:80]}", fill=(200, 150, 150), font=font_small)
                        draw.text((50, 170), "Navigation attempts exhausted", fill=(180, 180, 200), font=font_small)
                        draw.text((50, 200), "This may be due to site restrictions or browser compatibility", fill=(150, 150, 170), font=font_small)
                        
                        placeholder.save(error_path)
                        print(f"[DEBUG] Safari navigation error placeholder created: {error_path}")
                        
                        # Update the path to use the error image
                        path = error_path
                        
                    except Exception as placeholder_error:
                        print(f"[ERROR] Failed to create error placeholder: {placeholder_error}")
                        # Fallback to basic error handling
                        raise e

                
                print(f"[DEBUG] REACHED SCREENSHOT PHASE for {url}", flush=True)

                # 2. Optimized Hybrid Scroll (Lazy Load Trigger)
                # Scrolls 1000px steps, stops if hits bottom.
                await page.evaluate("""async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        const distance = 800;
                        const timer = setInterval(() => {
                            const scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if(totalHeight >= scrollHeight - window.innerHeight){
                                clearInterval(timer);
                                resolve();
                            }
                        }, 150); // Slower scroll (150ms) to allow rendering
                    });
                }""")
                
                await page.wait_for_timeout(2000) # Longer buffer for lazy loading
                await page.evaluate("() => window.scrollTo(0, 0)")
                await page.wait_for_timeout(1000) # Wait for stickies to reset

                path = f"{session_folder}/{browser_name}/{unique}__{w}x{h}.png"
                
                # Safari-specific screenshot handling - SIMPLIFIED
                if browser_name.lower() == "safari":
                    try:
                        print(f"[DEBUG] Attempting Safari screenshot for {url}")
                        await page.screenshot(path=path, full_page=True, timeout=30000)
                        print(f"[DEBUG] Safari screenshot successful: {path}")
                    except Exception as e:
                        print(f"[ERROR] Safari screenshot failed: {e}")
                        # Fallback to viewport if full page fails
                        try:
                            print(f"[DEBUG] Retrying Safari screenshot (viewport only)...")
                            await page.screenshot(path=path, full_page=False, timeout=15000)
                            print(f"[DEBUG] Safari viewport screenshot successful")
                        except Exception as ve:
                             print(f"[ERROR] Safari viewport screenshot also failed: {ve}")
                             # Placeholder creation could go here if needed
                else:
                    # Standard screenshot for Chrome/Edge/Firefox
                    try:
                        await page.screenshot(path=path, full_page=True)
                        print(f"[DEBUG] Standard screenshot successful: {path}")
                    except Exception as e:
                        print(f"[ERROR] Standard screenshot failed for {url}: {e}")

                
                # Offload image processing (keep usage of original path for worker if needed, 
                # but here we just optimize for upload/storage. 
                # Worker `add_browser_frame` might expect PNG? 
                # Let's check `add_browser_frame`. It opens image. Pillow opens webp fine.
                # But we'll optimize AFTER capturing and BEFORE uploading.
                
                # OPTIMIZE: Convert to WebP
                upload_path = path
                upload_filename = os.path.basename(path)
                content_type = "image/png"
                
                try:
                    webp_path = path.replace(".png", ".webp")
                    with Image.open(path) as img:
                        img.save(webp_path, "WEBP", quality=80, optimize=True)
                    
                    # Verify it saved
                    if os.path.exists(webp_path):
                        # Remove original PNG to save space
                        os.remove(path)
                        upload_path = webp_path
                        upload_filename = os.path.basename(webp_path)
                        content_type = "image/webp"
                except Exception as opt_err:
                    print(f"Image Optimization Failed: {opt_err}")
                    # Fallback to PNG (path)

                # Offload image processing (async worker)
                loop = asyncio.get_running_loop()
                # Updated to pass upload_path which might be WebP
                print(f"[DEBUG] Main: calling add_browser_frame for {upload_path}", flush=True)
                
                try:
                    await loop.run_in_executor(executor, add_browser_frame, upload_path, url)
                    print(f"[DEBUG] Main: add_browser_frame finished for {upload_path}", flush=True)
                except Exception as frame_error:
                    print(f"[ERROR] add_browser_frame failed for {upload_path}: {frame_error}", flush=True)
                    # Don't fail the whole audit if just the frame fails

                # Update progress in database - Best effort
                # Use a fresh session for this write to avoid concurrency issues with shared session
                db_new = database.SessionLocal()
                try:
                    # Local Path
                    screenshot_path = f"/screenshots/{session_id}/{browser_name}/{upload_filename}"
                    
                    # Save result
                    result_record = models.StaticAuditResult(
                        session_id=session_id,
                        url=url,
                        browser=browser_name.title(), # Ensure Title Case (e.g. Safari)
                        resolution=f"{w}x{h}",
                        screenshot_path=screenshot_path,
                        filename=upload_filename # Store optimized filename
                    )
                    db_new.add(result_record)
                    
                    # Update progress
                    session_record = db_new.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session_record:
                        session_record.completed += 1
                        
                    db_new.commit()
                    print(f"[DB] Saved result for {url} in {browser_name}", flush=True)
                except Exception as progress_error:
                    print(f"[ERROR] Progress update error for {url}: {progress_error}", flush=True)
                    db_new.rollback()
                finally:
                    db_new.close()

                print(f"[STATIC][{browser_name}] {url} @ {w}x{h} — DONE")
                    
#                 except Exception as e:
#                     print(f"[STATIC][{browser_name}] FAILED {url} @ {w}x{h}: {e}")

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                launch_args = {"headless": True}
                
                if browser_name == "Chrome":
                    launch_args["channel"] = "chrome"
                elif browser_name == "Edge":
                    launch_args["channel"] = "msedge"
                elif browser_name.lower() == "safari":
                # WebKit MUST be launched without Chromium flags
                    launch_args = {
                        "headless": True
                        }


                try:
                    browser = await browser_map[browser_name].launch(**launch_args)
                    print(f"[DEBUG] Successfully launched {browser_name}")
                except Exception as launch_error:
                    print(f"[ERROR] Failed to launch {browser_name}: {launch_error}")
                    # Log the error to database and continue with other browsers
                    try:
                        error_result = models.StaticAuditResult(
                            session_id=session_id,
                            url="BROWSER_LAUNCH_ERROR",
                            browser=browser_name,
                            resolution="ALL",
                            screenshot_path="/static/svg/error.svg",
                            filename=f"ERROR: {str(launch_error)}"
                        )
                        db.add(error_result)
                        db.commit()
                    except:
                        pass
                    return
                
                # Create context with browser-specific settings
                context_args = {"viewport": {"width": 1280, "height": 720}}  # Default viewport
                if browser_name.lower() == "safari":
                    context_args.update({
                        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                        "bypass_csp": True,  # Bypass Content Security Policy
                        "ignore_https_errors": True  # Ignore SSL certificate errors
                    })
                
                context = await browser.new_context(**context_args)
                
                tasks = []
                # Create a worker function to manage page lifecycle
                async def worker(url, w, h):
                    async with sem:
                        try:
                            # Create page with proper viewport size for this specific task
                            page = await context.new_page()
                            await page.set_viewport_size({"width": w, "height": h})
                            await process_url(page, url, w, h, browser_name)
                            await page.close()
                        except Exception as e:
                            import traceback
                            print(f"Worker error for {url}: {e}")
                            traceback.print_exc()
                            # Make sure page is cleaned up even if there's an error
                            try:
                                await page.close()
                            except:
                                pass

                for url in urls:
                    for w, h in resolutions:
                         tasks.append(worker(url, w, h))
                
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(b) for b in browsers])

        # Mark as completed unless stopped
        db.expire_all()
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            if session.status != "stopped":
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                db.commit()
            else:
                print(f"[STATIC] Session {session_id} ended with STOPPED status.")
            
    except Exception as e:
        print(f"Static audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    # Clean up running tasks
    if session_id in running_tasks:
        del running_tasks[session_id]
        
    print(f"STATIC SESSION {session_id} COMPLETED")

# ========== DYNAMIC AUDIT FUNCTIONS ==========

async def record_videos_async(urls: List[str], selected_browsers: List[str], 
                              selected_resolutions: List[Tuple[int, int]], 
                              session_id: str, user_id: int, db: Session, access_token: str = None):
    session_folder = f"videos/{session_id}"
    os.makedirs(session_folder, exist_ok=True)

    with open(f"{session_folder}/config.json", "w") as f:
        json.dump({
            "urls": urls,
            "browsers": selected_browsers,
            "resolutions": [f"{w}x{h}" for w, h in selected_resolutions],
            "type": "dynamic"
        }, f)

    try:
        async with async_playwright() as p:
            browser_map = {
                "Chrome": p.chromium,
                "Edge": p.chromium,
                "chrome": p.chromium,
                "chromium": p.chromium,
                "edge": p.chromium,
                "msedge": p.chromium
            }

            # AGGRESSIVE OPTIMIZATION: 3 Videos in parallel (High cpu load)
            sem = asyncio.Semaphore(3)
            
            async def process_video(page, url, w, h, browser_name, unique_name):
                 # Check if task was stopped - expire cache to get fresh status
                db.expire_all()
                session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                if session and session.status == "stopped":
                    print(f"[STOP] Dynamic audit stopped for {session_id}")
                    return

                try:
                    video_path_local = await record_fullpage_video(page, url, w, h, session_folder, browser_name, unique_name)
                    
                    # Video Path (Local)
                    video_url = f"/videos/{session_id}/{browser_name}/{os.path.basename(video_path_local)}"
                    
                    # Supabase upload removed - using local storage
                    print(f"[DYNAMIC] Final Video URL: {video_url}")
                    # Save result to DB
                    result = models.DynamicAuditResult(
                        session_id=session_id,
                        url=url,
                        browser=browser_name,
                        resolution=f"{w}x{h}",
                        video_path=video_url,
                        filename=os.path.basename(video_path_local)
                    )
                    db.add(result)

                    # Update progress in database - Best effort
                    try:
                        session.completed += 1
                        db.commit()
                    except:
                        db.rollback()
                            
                except Exception as e:
                    print(f"[DYNAMIC][{browser_name}] ERROR: {url} @ {w}x{h} → {e}")

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                browser = await browser_map[browser_name].launch(headless=True)
                
                # Create context
                context = await browser.new_context(viewport={"width": 1280, "height": 720})  # Default viewport
                
                tasks = []
                async def worker(url, w, h):
                    async with sem:
                        try:
                            page = await context.new_page()
                            await page.set_viewport_size({"width": w, "height": h})  # Set viewport for this specific task
                            unique_name = get_unique_filename(url)
                            await process_video(page, url, w, h, browser_name, unique_name)
                            await page.close()
                        except Exception as e:
                            print(f"Dynamic worker error for {url} @ {w}x{h}: {e}")
                            # Make sure page is cleaned up even if there's an error
                            try:
                                await page.close()
                            except:
                                pass

                for url in urls:
                    for w, h in selected_resolutions:
                        tasks.append(worker(url, w, h))
                
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(name) for name in selected_browsers if name in browser_map])
            
        # Mark as completed unless stopped
        db.expire_all()
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            if session.status != "stopped":
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                db.commit()
            else:
                print(f"[DYNAMIC] Session {session_id} ended with STOPPED status.")
            
    except Exception as e:
        print(f"Dynamic audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    
    # Clean up running tasks
    if session_id in running_tasks:
        del running_tasks[session_id]
        
    print(f"DYNAMIC SESSION {session_id} COMPLETED")

async def record_fullpage_video(page, url: str, w: int, h: int, session_folder: str, browser_name: str, unique_name: str):
    """Record a full-page video with scrolling and mouse movement."""
    try:
        await page.set_viewport_size({"width": w, "height": h})
        
        # 1. Smarter Navigation
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
             pass 
        
        # Short stabilization
        await asyncio.sleep(1.0)
        
        # Get page height for scrolling
        page_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = h
        
        # Optimized Scroll Steps: Larger steps, faster
        step_size = int(viewport_height * 0.9) 
        scroll_steps = max(1, page_height // step_size)
        
        frames_dir = f"temp_frames/{unique_name}_{browser_name}_{w}x{h}"
        os.makedirs(frames_dir, exist_ok=True)
        
        frame_count = 0
        
        # Record initial view
        await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
        frame_count += 1
        
        # Simulate scrolling
        current_scroll = 0
        for step in range(scroll_steps + 1): 
            current_scroll += step_size
            if current_scroll > page_height:
                current_scroll = page_height
                
            await page.evaluate(f"window.scrollTo(0, {current_scroll})")
            
            # Very fast wait
            await asyncio.sleep(0.2)
            
            # Simple mouse wiggle
            mouse_x = random.randint(100, w - 100)
            mouse_y = random.randint(100, viewport_height - 100)
            await page.mouse.move(mouse_x, mouse_y)
            # No extra sleep, just capture
            
            # Take screenshot
            await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
            frame_count += 1
            
            if current_scroll >= page_height:
                break
        
        # Scroll back to top
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        await page.screenshot(path=f"{frames_dir}/frame_{frame_count:04d}.png")
        frame_count += 1
        
        # Create video from frames
        video_path = f"{session_folder}/{browser_name}/{unique_name}__{w}x{h}.mp4"
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        
        # Use imageio to create video
        images = []
        for i in range(frame_count):
            img_path = f"{frames_dir}/frame_{i:04d}.png"
            if os.path.exists(img_path):
                images.append(imageio.imread(img_path))
        
        if images:
            # Offload video generation to thread pool
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                executor,
                functools.partial(imageio.mimsave, video_path, images, fps=3) # Higher FPS for smoother look
            )
            print(f"Video saved: {video_path}")
            
            # Clean up temp frames
            shutil.rmtree(frames_dir, ignore_errors=True)
            
            return video_path
        return None
        
    except Exception as e:
        print(f"Error recording video for {url}: {e}")
        raise

# ========== H1 AUDIT FUNCTIONS ==========

async def audit_h1_tags(urls: List[str], session_id: str, user_id: int, db: Session):
    """Audit H1 tags using Playwright to ensure JS-rendered content is captured"""
    from playwright.async_api import async_playwright
    from utils.security import is_safe_url

    try:
        async with async_playwright() as p:
            # Launch browser with stealth-like args
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            
            # Lower concurrency for browser tasks vs simple HTTP
            sem = asyncio.Semaphore(4)
            completed_count = 0

            async def process_one(url: str):
                nonlocal completed_count
                async with sem:
                    if not is_safe_url(url):
                        db.add(models.H1AuditResult(session_id=session_id, url=url, h1_count=0, h1_texts="[]", issues=json.dumps(["URL blocked (Private IP)"])))
                        return

                    # Check stopped status
                    db.expire_all()
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped": return

                    page = None
                    try:
                        page = await context.new_page()
                        # Wait for network idle to handle redirects/loading
                        try:
                            await page.goto(url, wait_until="networkidle", timeout=45000)
                        except Exception:
                            # Fallback if networkidle times out, just load
                            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        
                        # Explicitly wait for H1 to appear (handles JS rendering)
                        try:
                             await page.wait_for_selector("h1", timeout=5000)
                        except:
                             pass # Proceed to check count (will be 0 if not found)

                        # Brief wait for hydration/fonts
                        await page.wait_for_timeout(2000)
                        
                        # Extract H1s
                        h1_data = await page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('h1')).map(el => ({
                                text: el.innerText.trim(),
                                length: el.innerText.trim().length,
                                html: el.outerHTML
                            }));
                        }""")
                        
                        # Process results
                        h1_texts = [h['text'] for h in h1_data if h['text']]
                        h1_count = len(h1_texts) # Only count visible text H1s? Or all? User wants tag detection.
                        # Let's count all tags found in DOM
                        h1_cnt_raw = len(h1_data)
                        
                        issues = []
                        if h1_cnt_raw == 0:
                            issues.append("No H1 tag found")
                        elif h1_cnt_raw > 1:
                            issues.append(f"Multiple H1 tags found ({h1_cnt_raw})")
                            
                        for h in h1_data:
                            if not h['text']:
                                issues.append("Empty H1 tag")
                            else:
                                if h['length'] > 70: issues.append(f"H1 too long ({h['length']} chars)")
                                if h['length'] < 10: issues.append(f"H1 too short ({h['length']} chars)")
                        
                        db.add(models.H1AuditResult(
                            session_id=session_id,
                            url=url,
                            h1_count=h1_cnt_raw,
                            h1_texts=json.dumps(h1_texts),
                            issues=json.dumps(issues)
                        ))
                        
                    except Exception as e:
                        print(f"H1 Playwright Error {url}: {e}")
                        db.add(models.H1AuditResult(session_id=session_id, url=url, h1_count=0, h1_texts="[]", issues=json.dumps([f"Error: {str(e)}"])))
                    finally:
                        if page: await page.close()
                    
                    completed_count += 1
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed = completed_count
                    db.commit()

            await asyncio.gather(*[process_one(url) for url in urls])
            
            # Finalize
            db.expire_all()
            session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if session:
                db.refresh(session)
                if session.status != "stopped":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                    db.commit()
                else:
                    print(f"[H1] Session {session_id} ended with STOPPED status.")
                    
    except Exception as e:
        print(f"H1 Audit Fatal: {e}")
        db.refresh(session)
        session.status = "error"
        db.commit()
    finally:
        db.close()
    
    print(f"H1 AUDIT SESSION {session_id} COMPLETED")

# ========== PHONE NUMBER AUDIT FUNCTIONS ==========

async def audit_phone_numbers(urls: List[str], target_numbers: List[str], options: List[str], 
                               session_id: str, user_id: int, db: Session):
    """Audit phone numbers on multiple URLs using high-performance parallel fetches"""
    import httpx
    from bs4 import BeautifulSoup
    from utils.security import is_safe_url

    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        async with httpx.AsyncClient(timeout=30, follow_redirects=True, verify=True) as client:
            sem = asyncio.Semaphore(10)
            completed_count = 0

            async def process_one(url: str):
                nonlocal completed_count
                async with sem:
                    if not is_safe_url(url): 
                        db.add(models.PhoneAuditResult(session_id=session_id, url=url, phone_count=0, issues=json.dumps(["URL blocked for security (Private IP)"])))
                        return
                    
                    db.refresh(session)
                    if session.status == "stopped": return

                    try:
                        resp = await client.get(url)
                        soup = BeautifulSoup(resp.text, "html.parser")
                        
                        # Extract regions
                        header = soup.find('header')
                        footer = soup.find('footer')
                        
                        header_text = header.get_text() if header else ""
                        footer_text = footer.get_text() if footer else ""
                        body_text = soup.body.get_text() if soup.body else ""

                        found_data = []
                        seen = set()
                        
                        for num in target_numbers:
                            num_clean = num.strip()
                            if not num_clean: continue
                            
                            location = "Body"
                            if num_clean in header_text: location = "Header"
                            elif num_clean in footer_text: location = "Footer"
                            elif num_clean in body_text: location = "Body"
                            else: continue
                            
                            if num_clean not in seen:
                                seen.add(num_clean)
                                found_data.append({"number": num_clean, "location": location})

                        db.add(models.PhoneAuditResult(
                            session_id=session_id,
                            url=url,
                            phone_numbers=json.dumps(found_data),
                            phone_count=len(found_data),
                            formats_detected=json.dumps(["Standard"]),
                            issues=json.dumps([])
                        ))
                    except Exception as e:
                        print(f"Phone Error {url}: {e}")
                        db.add(models.PhoneAuditResult(session_id=session_id, url=url, phone_count=0, issues=json.dumps([str(e)])))
                    
                    completed_count += 1
                    session.completed = completed_count
                    db.commit()

            await asyncio.gather(*[process_one(url) for url in urls])
            
            db.expire_all()
            if session:
                 db.refresh(session)
                 if session.status != "stopped":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                    db.commit()
                 else:
                    print(f"[PHONE] Session {session_id} ended with STOPPED status.")
            
    except Exception as e:
        print(f"Phone Audit Fatal: {e}")
        db.refresh(session)
        session.status = "error"
        db.commit()
    finally:
        db.close()
    
    print(f"PHONE AUDIT SESSION {session_id} COMPLETED")

# ========== HELPER FUNCTIONS ==========
def add_browser_frame(img_path: str, url: str):
    """Add browser frame with URL bar to screenshot."""
    print(f"[DEBUG] add_browser_frame called for {img_path}", flush=True)
    try:
        img = Image.open(img_path)
        width, height = img.size
        
        # Create new image with frame
        frame_height = 80
        new_height = height + frame_height
        new_img = Image.new('RGB', (width, new_height), color='white')
        
        # Draw browser frame
        draw = ImageDraw.Draw(new_img)
        
        # Browser top bar
        draw.rectangle([(0, 0), (width, 40)], fill='#f1f3f4')
        
        # Browser controls (circles)
        circle_radius = 6
        circle_spacing = 20
        start_x = 20
        
        colors = ['#ff5f56', '#ffbd2e', '#27ca3f']
        for i, color in enumerate(colors):
            x0 = start_x + i * circle_spacing - circle_radius
            y0 = 20 - circle_radius
            x1 = start_x + i * circle_spacing + circle_radius
            y1 = 20 + circle_radius
            draw.ellipse([(x0, y0), (x1, y1)], fill=color)
        
        # URL bar
        url_bar_height = 30
        url_bar_y = 45
        draw.rectangle([(60, url_bar_y), (width - 20, url_bar_y + url_bar_height)], 
                      fill='#e8eaed', outline='#dadce0', width=1)
        
        # Add URL text (truncate if too long)
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Truncate URL if too long
        max_url_width = width - 90
        url_text = url
        bbox = draw.textbbox((0, 0), url_text, font=font)
        text_width = bbox[2] - bbox[0]
        
        if text_width > max_url_width:
            # Truncate with ellipsis
            while text_width > max_url_width and len(url_text) > 10:
                url_text = url_text[:-1]
                bbox = draw.textbbox((0, 0), url_text + "...", font=font)
                text_width = bbox[2] - bbox[0]
            url_text = url_text + "..."
        
        draw.text((70, url_bar_y + 8), url_text, fill='#5f6368', font=font)
        
        # Paste original image below frame
        new_img.paste(img, (0, frame_height))
        
        # Save
        new_img.save(img_path)
        print(f"Added browser frame to: {img_path}")
        
    except Exception as e:
        print(f"Error adding browser frame: {e}")

# ========== BACKGROUND TASKS ==========

def static_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], 
                      session_id: str, user_id: int, session_name: str, access_token: str = None):
    selected_res = [(int(r.split('x')[0]), int(r.split('x')[1])) for r in resolutions]
    
    # Create database session
    db = database.SessionLocal()
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
             
        # Check if session already exists (e.g. restart)
        existing_session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id).first()
        
        if not existing_session:
            # Create session record
            session = models.AuditSession(
                session_id=session_id,
                user_id=user_id,
                session_type="static",
                name=session_name,
                urls=json.dumps(urls),
                browsers=json.dumps(browsers),
                resolutions=json.dumps(resolutions),
                total_expected=len(urls) * len(browsers) * len(resolutions),
                status="running"
            )
            db.add(session)
            db.commit()
        
        # Run the audit
        asyncio.run(capture_screenshots(urls, browsers, selected_res, session_id, user_id, db, access_token))
    finally:
        db.close()

def dynamic_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], 
                       session_id: str, user_id: int, session_name: str, access_token: str = None):
    selected_res = [(int(r.split('x')[0]), int(r.split('x')[1])) for r in resolutions]
    
    # Create database session
    db = database.SessionLocal()
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
             
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="dynamic",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps(browsers),
            resolutions=json.dumps(resolutions),
            total_expected=len(urls) * len([b for b in browsers if b in ["Chrome", "Edge"]]) * len(resolutions),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(record_videos_async(urls, browsers, selected_res, session_id, user_id, db, access_token))
    finally:
        db.close()

def h1_audit_task(urls: List[str], session_id: str, user_id: int, session_name: str):
    """Background task for H1 audit"""
    db = database.SessionLocal()
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
             
        # Create session record
        session = models.AuditSession(
            session_id=session_id,
            user_id=user_id,
            session_type="h1",
            name=session_name,
            urls=json.dumps(urls),
            browsers=json.dumps([]),
            resolutions=json.dumps([]),
            total_expected=len(urls),
            status="running"
        )
        db.add(session)
        db.commit()
        
        # Run the audit
        asyncio.run(audit_h1_tags(urls, session_id, user_id, db))
    finally:
        db.close()


def audit_performance_task(urls: List[str], session_id: str, strategy: str = "desktop"):
    """Sync wrapper to run performance audit in a private thread with Proactor loop"""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(_audit_performance_task_logic(urls, session_id, strategy))

async def _audit_performance_task_logic(urls: List[str], session_id: str, strategy: str = "desktop"):
    """Background task for Performance audit using modern Async Playwright"""
    print(f"DEBUG: Starting async performance audit for {session_id}")
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            # Control concurrency
            sem = asyncio.Semaphore(3)
            completed_count = 0

            async def run_single_audit(url: str):
                nonlocal completed_count
                async with sem:
                    # Check if stopped - expire cache to get fresh status
                    db.expire_all()
                    db.refresh(session)
                    if session.status == "stopped":
                        print(f"[STOP] Performance audit stopped for session {session_id}")
                        return

                    try:
                        context = await browser.new_context(
                            **(p.devices['iPhone 12'] if strategy == "mobile" else {})
                        )
                        page = await context.new_page()
                        
                        start_time = datetime.utcnow()
                        await page.goto(url, wait_until="load", timeout=60000)
                        
                        # Capture modern metrics via JS
                        metrics = await page.evaluate("""() => {
                            const timing = performance.timing;
                            const paint = performance.getEntriesByType('paint');
                            const fcp = paint.find(p => p.name === 'first-contentful-paint');
                            
                            return {
                                ttfb: timing.responseStart - timing.navigationStart,
                                dom_load: timing.domContentLoadedEventEnd - timing.navigationStart,
                                page_load: timing.loadEventEnd - timing.navigationStart,
                                fcp: fcp ? fcp.startTime : 0,
                                resources: performance.getEntriesByType('resource').length
                            };
                        }""")
                        
                        # Scoring Logic (0-100)
                        score = 100
                        if metrics['page_load'] > 2500: score -= 20
                        if metrics['page_load'] > 5000: score -= 20
                        if metrics['ttfb'] > 600: score -= 15
                        if metrics['fcp'] > 2000: score -= 15
                        if metrics['resources'] > 100: score -= 10
                        score = max(0, score)

                        result = models.PerformanceAuditResult(
                            session_id=session_id,
                            url=url,
                            device_preset="Mobile" if strategy == "mobile" else "Desktop",
                            ttfb=int(metrics['ttfb']),
                            fcp=int(metrics['fcp']),
                            dom_load=int(metrics['dom_load']),
                            page_load=int(metrics['page_load']),
                            resource_count=metrics['resources'],
                            score=score
                        )
                        db.add(result)
                        
                        completed_count += 1
                        session.completed = completed_count
                        db.commit()
                        
                        await page.close()
                        await context.close()
                    except Exception as e:
                        print(f"Perf Audit Error for {url}: {e}")
                        db.add(models.PerformanceAuditResult(session_id=session_id, url=url, score=0))
                        completed_count += 1
                        session.completed = completed_count
                        db.commit()

            await asyncio.gather(*[run_single_audit(url) for url in urls])
            
            db.expire_all()
            if session:
                db.refresh(session)
                if session.status != "stopped":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                    db.commit()
                else:
                    print(f"[PERF] Session {session_id} ended with STOPPED status.")
            await browser.close()
            
    except Exception as e:
        print(f"Performance Audit Fatal: {e}")
        db.refresh(session)
        session.status = "error"
        db.commit()
    finally:
        db.close()

async def audit_meta_tags_logic(urls: List[str], session_id: str):
    """Background task for Meta Tags audit using raw HTTP + Regex to avoid Playwright overhead/bugs"""
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        import httpx
        
        async with httpx.AsyncClient(follow_redirects=True, verify=True) as client:
            completed_count = 0
            from bs4 import BeautifulSoup
            
            for url in urls:
                # Check if stopped - expire cache to get fresh status
                db.expire_all()
                db.refresh(session)
                if session.status == "stopped":
                    print(f"[STOP] Meta tags audit stopped for session {session_id}")
                    break
                
                try:
                    resp = await client.get(url, timeout=30)
                    html = resp.text
                    soup = BeautifulSoup(html, "html.parser")
                    
                    # Title
                    title = soup.title.string.strip() if soup.title and soup.title.string else ""
                    
                    # Description
                    description = ""
                    desc_tag = soup.find("meta", attrs={"name": "description"}) or \
                               soup.find("meta", attrs={"property": "description"})
                    if desc_tag:
                        description = desc_tag.get("content", "").strip()
                    
                    # Keywords
                    keywords = ""
                    kw_tag = soup.find("meta", attrs={"name": "keywords"})
                    if kw_tag:
                        keywords = kw_tag.get("content", "").strip()
                    
                    # Canonical
                    canonical = ""
                    canon_tag = soup.find("link", rel="canonical")
                    if canon_tag:
                        canonical = canon_tag.get("href", "").strip()
                    
                    # OG Tags
                    og_tags = {}
                    for tag in soup.find_all("meta", property=re.compile(r'^og:')):
                        og_tags[tag.get("property")] = tag.get("content", "")

                    # Twitter Tags
                    twitter_tags = {}
                    for tag in soup.find_all("meta", attrs={"name": re.compile(r'^twitter:')}):
                        twitter_tags[tag.get("name")] = tag.get("content", "")
                    
                    # Schema
                    schema_tags = []
                    for script in soup.find_all("script", type="application/ld+json"):
                        try:
                            schema_tags.append(json.loads(script.string))
                        except: pass
                    
                    # --- Rich Analysis ---
                    from collections import Counter
                    def tokenize(text):
                        if not text: return []
                        return [w.lower() for w in re.findall(r'[a-zA-Z]{3,}', text)]
                    
                    # Extract visible text accurately
                    for script_or_style in soup(["script", "style"]):
                        script_or_style.decompose()
                    body_text = soup.get_text(separator=' ')
                    
                    body_tokens = tokenize(body_text)
                    body_counts = Counter(body_tokens)
                    
                    target_keywords = tokenize(title + " " + keywords + " " + description)
                    target_keywords = list(set(target_keywords))
                    
                    keyword_consistency = {kw: body_counts.get(kw, 0) for kw in target_keywords}
                        
                    # Validation
                    warnings = []
                    missing_tags = []
                    score = 100
                    
                    if not title:
                        missing_tags.append("Title")
                        score -= 20
                    elif len(title) < 30 or len(title) > 60:
                        warnings.append(f"Title length ({len(title)}) is suboptimal. Recommended: 30-60.")
                        score -= 5
                        
                    if not description:
                        missing_tags.append("Description")
                        score -= 20
                    elif len(description) < 70 or len(description) > 155:
                        warnings.append(f"Description length ({len(description)}) is suboptimal. Recommended: 70-155.")
                        score -= 5
                        
                    if not canonical:
                        warnings.append("Missing Canonical URL.")
                        score -= 10
                        
                    if not og_tags:
                        warnings.append("Missing Open Graph tags.")
                        score -= 10
                        
                    score = max(0, score)
                    
                    result = models.MetaTagsResult(
                        session_id=session_id,
                        url=url,
                        title=title,
                        description=description,
                        keywords=keywords,
                        canonical=canonical,
                        og_tags=json.dumps(og_tags),
                        twitter_tags=json.dumps(twitter_tags),
                        schema_tags=json.dumps(schema_tags),
                        missing_tags=json.dumps(missing_tags),
                        warnings=json.dumps(warnings),
                        keyword_consistency=json.dumps(keyword_consistency),
                        score=score
                    )
                    db.add(result)
                    db.commit()
                    
                except Exception as e:
                    print(f"Meta audit failed for {url}: {e}")
                
                completed_count += 1
                session.completed = completed_count
                db.commit()

            db.expire_all()
            if session:
                db.refresh(session)
                if session.status != "stopped":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                    db.commit()
                else:
                    print(f"[META] Session {session_id} ended with STOPPED status.")
    except Exception as e:
        print(f"Meta tags audit failed: {e}")
        session.status = "error"
        db.commit()
    finally:
        db.close()



def audit_accessibility_task(urls: List[str], session_id: str):
    """Sync wrapper to run accessibility audit in a private thread with Proactor loop"""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(_audit_accessibility_task_logic(urls, session_id))

async def _audit_accessibility_task_logic(urls: List[str], session_id: str):
    """Background task for Accessibility audit using modern Async Playwright"""
    print(f"DEBUG: Starting async accessibility audit for {session_id}")
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return
        
        # Fetch axe-core once
        axe_source = ""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.0/axe.min.js", timeout=10)
                axe_source = resp.text
        except Exception as e:
            print(f"Failed to fetch axe-core: {e}")
            session.status = "error"
            db.commit()
            return

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            sem = asyncio.Semaphore(3) # Parallel audits
            completed_count = 0

            async def run_single_a11y(url: str):
                nonlocal completed_count
                async with sem:
                    # Check if stopped - expire cache to get fresh status
                    db.expire_all()
                    db.refresh(session)
                    if session.status == "stopped":
                        print(f"[STOP] Accessibility audit stopped for {session_id}")
                        return
                    
                    try:
                        page = await browser.new_page()
                        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        
                        # Inject and run axe
                        await page.evaluate(axe_source)
                        results = await page.evaluate("axe.run()")
                        
                        violations = results.get('violations', [])
                        
                        # Calculate Score
                        critical = sum(1 for v in violations if v.get('impact') == 'critical')
                        serious = sum(1 for v in violations if v.get('impact') == 'serious')
                        moderate = sum(1 for v in violations if v.get('impact') == 'moderate')
                        minor = sum(1 for v in violations if v.get('impact') == 'minor')
                        
                        score = max(0, 100 - (critical * 10 + serious * 5 + moderate * 2))
                        
                        res_entry = models.AccessibilityAuditResult(
                            session_id=session_id,
                            url=url,
                            score=score,
                            violations_count=len(violations),
                            critical_count=critical,
                            serious_count=serious,
                            moderate_count=moderate,
                            minor_count=minor,
                            report_json=json.dumps(violations) 
                        )
                        db.add(res_entry)
                        
                        completed_count += 1
                        session.completed = completed_count
                        db.commit()
                        await page.close()
                    except Exception as e:
                        print(f"A11y error {url}: {e}")
                        db.add(models.AccessibilityAuditResult(session_id=session_id, url=url, score=0))
                        completed_count += 1
                        session.completed = completed_count
                        db.commit()

            await asyncio.gather(*[run_single_a11y(url) for url in urls])
            
            db.expire_all()
            if session:
                db.refresh(session)
                if session.status != "stopped":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                    db.commit()
                else:
                    print(f"[A11Y] Session {session_id} ended with STOPPED status.")
            await browser.close()
            
    except Exception as e:
        print(f"Accessibility Audit Fatal: {e}")
        db.refresh(session)
        session.status = "error"
        db.commit()
    finally:
        db.close()

async def audit_phone_numbers(urls: List[str], target_numbers: List[str], options: List[str], 
                               session_id: str, user_id: int, db: Session):
    """Audit phone numbers - discover and validate phone numbers and tel: tags on URLs"""
    import re
    import phonenumbers
    from phonenumbers import PhoneNumberMatcher
    
    try:
        async with async_playwright() as p:
            # Enhanced stealth and compatibility
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            
            for url in urls:
                try:
                    # Check if session was stopped - expire cache to get fresh status
                    db.expire_all()
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        print(f"[STOP] Phone audit stopped for {session_id}")
                        break
                    
                    print(f"[CTA AUDIT] Discovering numbers on {url}")
                    
                    page = await context.new_page()
                    await page.goto(url, wait_until="networkidle", timeout=45000)
                    
                    # Get page content and text
                    content = await page.content()
                    text_content = await page.inner_text('body')
                    
                    discovered_numbers = []
                    found_clean_set = set()
                    
                    # 1. DISCOVER TEL: TAGS (High Signal)
                    tel_links = await page.eval_on_selector_all('a[href^="tel:"]', "elements => elements.map(el => ({ href: el.href, text: el.innerText }))")
                    
                    for link in tel_links:
                        raw_href = link['href'].replace('tel:', '').split('?')[0].strip()
                        try:
                            # Parse and format the number from href
                            parsed = phonenumbers.parse(raw_href, None) # None for international or with +
                            if phonenumbers.is_valid_number(parsed):
                                clean_num = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                                if clean_num not in found_clean_set:
                                    found_clean_set.add(clean_num)
                                    discovered_numbers.append({
                                        'number': phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
                                        'clean': clean_num,
                                        'type': 'Link (tel:)',
                                        'valid': True,
                                        'location': 'Anchor Tag',
                                        'source_text': link['text'].strip() or 'Icon/Empty'
                                    })
                        except:
                            # If not parsable, keep raw if it looks like a number
                            discovered_numbers.append({
                                'number': raw_href,
                                'clean': re.sub(r'\D', '', raw_href),
                                'type': 'Link (tel:)',
                                'valid': False,
                                'location': 'Anchor Tag',
                                'source_text': link['text'].strip() or 'Icon/Empty'
                            })

                    # 2. DISCOVER TEXT PATTERNS (Regex/Heuristic)
                    # We use phonenumbers.PhoneNumberMatcher for robust extraction
                    # Defaulting to "US" for common patterns if no prefix, but matcher handles many
                    for match in PhoneNumberMatcher(text_content, "US"):
                        clean_num = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
                        if clean_num not in found_clean_set:
                            found_clean_set.add(clean_num)
                            discovered_numbers.append({
                                'number': phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
                                'clean': clean_num,
                                'type': 'Plain Text',
                                'valid': True,
                                'location': 'Body',
                                'source_text': match.raw_string
                            })

                    # 3. HIGHLIGHT TARGET MATCHES
                    target_clean_list = [''.join(filter(str.isdigit, n)) for n in target_numbers]
                    for entry in discovered_numbers:
                        entry['is_target'] = entry['clean'].endswith(tuple(target_clean_list)) if target_clean_list else False

                    # 4. ADDITIONAL CHECKS
                    issues = []
                    if 'check_links' in options:
                        # Find numbers in text that AREN'T clickable
                        text_only = [n for n in discovered_numbers if n['type'] == 'Plain Text']
                        if text_only:
                            issues.append(f"Found {len(text_only)} non-clickable phone numbers in body text.")
                    
                    if 'check_schema' in options:
                        if 'itemprop="telephone"' not in content.lower() and '"telephone"' not in content.lower():
                            issues.append("Missing telephone schema markup (LD+JSON or Microdata).")

                    # Create result record
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_count=len(discovered_numbers),
                        phone_numbers=json.dumps(discovered_numbers),
                        formats_detected=json.dumps(list(set([n['type'] for n in discovered_numbers]))),
                        issues=json.dumps(issues)
                    )
                    db.add(result)
                    
                    # Update session progress
                    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session:
                        session.completed += 1
                    db.commit()
                    
                    await page.close()
                    
                except Exception as e:
                    print(f"Error auditing {url}: {e}")
                    result = models.PhoneAuditResult(
                        session_id=session_id,
                        url=url,
                        phone_count=0,
                        phone_numbers=json.dumps([]),
                        formats_detected=json.dumps([]),
                        issues=json.dumps([f"Error: {str(e)}"])
                    )
                    db.add(result)
                    db.commit()
            
            await browser.close()
            
            # Mark session as completed
            session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if session:
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                db.commit()
            
            print(f"CTA AUDIT SESSION {session_id} COMPLETED")
            
    except Exception as e:
        print(f"CTA Audit Fatal Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()

def phone_audit_task(urls: List[str], target_numbers: List[str], options: List[str], 
                     session_id: str, user_id: int, session_name: str):
    """Background task for phone audit"""
    db = database.SessionLocal()
    try:
        if sys.platform == 'win32':
             asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
             
        # Run the audit
        asyncio.run(audit_phone_numbers(urls, target_numbers, options, session_id, user_id, db))
    finally:
        db.close()

# ========== ROUTES ==========

@app.get("/")
async def home(request: Request, db: Session = Depends(auth.get_db)):
    """Root route - Landing page for guests, redirect to Dashboard for users"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        # Redirect to new SaaS Dashboard if authenticated
        return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    
    # Show Static Audit as the primary interactive page
    return templates.TemplateResponse("static.html", {
        "request": request, 
        "user": None
    })

@app.get("/dashboard")
async def dashboard(request: Request, user = Depends(require_auth)):
    """Dashboard route (legacy/redirect) - requires authentication"""
    return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)

@app.get("/platform/static")
async def static_audit_platform(request: Request, user = Depends(require_auth)):
    """Static Audit route - requires authentication"""
    return templates.TemplateResponse("static.html", {
        "request": request, 
        "user": user,
        "show_nav": True
    })

@app.get("/login")
async def login_page(request: Request, db: Session = Depends(auth.get_db)):
    """Login page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("login.html", {
        "request": request, 
        "google_client_id": settings.google_client_id
    })

@app.get("/logout")
async def logout_get():
    """Logout user and redirect to login page"""
    response = RedirectResponse(url="/?signin=true", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token", path="/")
    return response

@app.post("/api/auth/logout")
async def logout_post():
    """Logout user and redirect to login page"""
    response = RedirectResponse(url="/?signin=true", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key="access_token", path="/")
    return response

@app.get("/register")
async def register_page(request: Request, db: Session = Depends(auth.get_db)):
    """Register page - redirects to dashboard if already logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/platform/dashboard", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    return templates.TemplateResponse("register.html", {
        "request": request,
        "google_client_id": settings.google_client_id
    })

@app.get("/reset-password")
async def reset_password_page(request: Request):
    """Reset Password Page"""
    return templates.TemplateResponse("reset-password.html", {"request": request})

@app.get("/forgot-password")
async def forgot_password_redirect():
    """Redirect legacy forgot password link to reset password page"""
    return RedirectResponse(url="/reset-password")


@app.get("/platform/profile")
async def profile_page(request: Request, db: Session = Depends(auth.get_db)):
    """Profile page - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    # Fetch user stats
    total_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).count()
    completed_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "completed").count()

    stats = {
        "total_sessions": total_sessions,
        "completed_audits": completed_audits,
        "success_rate": int((completed_audits / total_sessions * 100)) if total_sessions > 0 else 0
    }

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "stats": stats
    })
        
@app.get("/responsive")
async def responsive_page(request: Request, user = Depends(require_auth)):
    """Responsive audit page - requires authentication"""
    return templates.TemplateResponse("static_snapshots.html", {"request": request, "user": user})

@app.get("/responsive/static")
async def static_audit_page(request: Request, user = Depends(require_auth)):
    """Static audit page - requires authentication"""
    return templates.TemplateResponse("static-audit.html", {"request": request, "user": user})

@app.get("/static-results/{session_id}")
async def static_results_view(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View static audit results - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Parse JSON fields
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except:
        pass
        
    # Get results from DB
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    
    # Serialize results for JS
    results_list = []
    for r in results:
        results_list.append({
            "url": r.url,
            "browser": r.browser,
            "resolution": r.resolution,
            "filename": r.filename,
            "screenshot_path": r.screenshot_path # Include full path/URL
        })
    
    import time
    cache_buster = int(time.time())  # Add timestamp to force cache invalidation
    
    return templates.TemplateResponse("static_report.html", {
        "request": request,
        "user": user,
        "session": session,
        "results": results,
        "results_data": json.dumps(results_list),
        "results_json": json.dumps([r.url for r in results]),
        "cache_buster": cache_buster  # Force browser to reload template
    })


@app.get("/dynamic-results/{session_id}")
async def dynamic_results_view(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View dynamic audit results - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Parse JSON fields
    try:
        if isinstance(session.urls, str):
            session.urls = json.loads(session.urls)
    except:
        session.urls = []

    try:
        if isinstance(session.browsers, str):
            session.browsers = json.loads(session.browsers)
    except:
        session.browsers = []

    try:
        if isinstance(session.resolutions, str):
            session.resolutions = json.loads(session.resolutions)
    except:
        session.resolutions = []

    # Get results from DB
    results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
    
    # Serialize results for JS
    results_list = []
    for r in results:
        results_list.append({
            "url": r.url,
            "browser": r.browser,
            "resolution": r.resolution,
            "video_path": r.video_path,
            "filename": r.filename
        })

    return templates.TemplateResponse("dynamic-results.html", {
        "request": request,
        "user": user,
        "session": session,
        "results": results, # Keep for backward compatibility if needed, though we use results_json now
        "results_json": json.dumps(results_list), 
    })

@app.get("/responsive/dynamic")
async def dynamic_audit_page(request: Request, user = Depends(require_auth)):
    """Dynamic audit page - requires authentication"""
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/h1-audit")
async def h1_audit_page(request: Request, user = Depends(require_auth)):
    """H1 audit page - requires authentication"""
    return templates.TemplateResponse("h1_tags.html", {"request": request, "user": user})

@app.get("/phone-audit")
async def phone_audit_page(request: Request, user = Depends(require_auth)):
    """Phone audit page - requires authentication"""
    return templates.TemplateResponse("phone_validator.html", {"request": request, "user": user})

@app.get("/platform/visual")
async def visual_page(request: Request, user = Depends(require_auth)):
    """Visual audit page - requires authentication"""
    return templates.TemplateResponse("visual_regression.html", {"request": request, "user": user})

@app.get("/platform/history", response_class=HTMLResponse)
async def history_view(request: Request, type: Optional[str] = None, page: int = 1, limit: int = 10, db: Session = Depends(auth.get_db)):
    """Unified Audit History page - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         return RedirectResponse("/login")
    
    # Get filter type (support both path param and query param)
    audit_type = type or request.query_params.get("type", "all")
    
    # Base query
    query = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id)
    
    # Apply filter with mapping for consistency
    if audit_type != "all":
        # Standardization mapping: UI/URL -> Database session_type
        db_type = audit_type
        mapping = {
            "responsive": "static",
            "meta-tags": "meta-tags",
            "cta": "phone",
            "speed": "performance"
        }
        db_type = mapping.get(audit_type, audit_type)
        query = query.filter(models.AuditSession.session_type == db_type)
        
    # Get total count before pagination
    total_count = query.count()
    
    # Calculate offset
    offset = (page - 1) * limit
    
    # Order by newest and apply pagination
    sessions = query.order_by(models.AuditSession.created_at.desc()).offset(offset).limit(limit).all()
    
    # Calculate total pages
    total_pages = (total_count + limit - 1) // limit
    
    return templates.TemplateResponse("audit_history.html", {
        "request": request, 
        "user": user,
        "sessions": sessions,
        "active_type": audit_type,
        "current_page": page,
        "total_pages": total_pages,
        "limit": limit
    })

# ========== API ROUTES ==========

@app.post("/api/auth/register")
async def register(
    request: RegisterRequest, 
    db: Session = Depends(auth.get_db)
):
    """Register new user using Supabase Auth"""
    try:
        # Check if username exists locally first (optional optimization)
        if db.query(models.User).filter(models.User.username == request.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")

        # Register locally
        user = auth.register_user(request.email, request.password, request.username, db)

        print(f"User created successfully: {user.id}, {user.username}")

        # Auto-login to get token
        login_data = auth.login_user(request.username, request.password, db)

        return {
            "access_token": login_data["access_token"],
            "token_type": "bearer",
            "user": {"id": user.id, "username": user.username}
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Registration error: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@app.post("/api/auth/login")
async def login(
    request: LoginRequest,
    db: Session = Depends(auth.get_db)
):
    """Login user and return access token with HttpOnly cookie"""
    print(f"Login attempt: {request.username}")
    
    try:
        # Authenticate locally with username
        login_data = auth.login_user(request.username, request.password, db)
        
        user = login_data["user"]
        
        # Create response with HttpOnly cookie (matching Google login)
        response = JSONResponse({
            "access_token": login_data["access_token"], 
            "token_type": "bearer", 
            "user": {"id": user.id, "username": user.username}
        })
        
        # Set HttpOnly cookie
        response.set_cookie(
            key="access_token",
            value=login_data["access_token"],
            httponly=True,
            max_age=settings.access_token_expire_minutes * 60,
            samesite="lax",
            secure=False  # Set to True in production with HTTPS
        )
        
        return response
        
    except Exception as e:
        print(f"Login error: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail="Incorrect username or password")

@app.post("/api/auth/google")
async def google_login(request: GoogleLoginRequest, db: Session = Depends(auth.get_db)):
    """Handle Google Login: Verify token, create/get user, issue local token"""
    try:
        # Verify Google Token
        id_info = id_token.verify_oauth2_token(
            request.token, 
            google_requests.Request(), 
            settings.google_client_id
        )
        
        email = id_info.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Google token missing email")
            
        # Check if user exists
        user = db.query(models.User).filter(models.User.email == email).first()
        
        if not user:
            # Register new user automatically
            username = email.split("@")[0]
            # Ensure unique username
            base_username = username
            counter = 1
            while db.query(models.User).filter(models.User.username == username).first():
                username = f"{base_username}{counter}"
                counter += 1
            
            # Create random password (user relies on Google Auth)
            random_password = str(uuid.uuid4())
            user = auth.register_user(email, random_password, username, db)
            print(f"Registered new Google user: {user.username}")
        
        # Create local access token
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = auth.create_access_token(
            data={"sub": user.id, "email": user.email},
            expires_delta=access_token_expires
        )
        
        # Set cookie
        response = JSONResponse({
            "access_token": access_token, 
            "token_type": "bearer",
            "user": {"id": user.id, "username": user.username}
        })
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            max_age=settings.access_token_expire_minutes * 60,
            samesite="lax",
            secure=False # Set to True in production with HTTPS
        )
        return response

    except ValueError as e:
        # Invalid token
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {str(e)}")
    except Exception as e:
        print(f"Google Login Error: {e}")
        raise HTTPException(status_code=500, detail="Authentication failed")

@app.get("/logout_legacy")
async def logout_legacy():
    """Legacy logout route"""
    return RedirectResponse(url="/logout")

# ========== PASSWORD RESET MODELS ==========

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

# ========== PASSWORD RESET ENDPOINTS ==========

@app.get("/forgot-password")
async def forgot_password_page(request: Request):
    """Render forgot password page"""
    return templates.TemplateResponse("forgot-password.html", {"request": request})

@app.post("/api/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(auth.get_db)):
    """Generate password reset token"""
    # Find user by email
    user = db.query(models.User).filter(models.User.email == request.email).first()
    
    if not user:
        # Don't reveal if email exists for security
        return JSONResponse({
            "message": "If the email exists, a reset link has been sent.",
            "reset_link": None
        })
    
    # Generate unique token
    import secrets
    token = secrets.token_urlsafe(32)
    
    # Set expiration (30 minutes from now)
    expires_at = datetime.utcnow() + timedelta(minutes=30)
    
    # Create reset token record
    reset_token = models.PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=expires_at
    )
    db.add(reset_token)
    db.commit()
    
    # For development: return the reset link
    reset_link = f"http://127.0.0.1:8000/reset-password/{token}"
    
    return JSONResponse({
        "message": "Password reset link generated successfully!",
        "reset_link": reset_link  # In production, this would be sent via email
    })

@app.get("/reset-password/{token}")
async def reset_password_page(token: str, request: Request, db: Session = Depends(auth.get_db)):
    """Render reset password page with token validation"""
    # Validate token exists and is not expired
    reset_token = db.query(models.PasswordResetToken).filter(
        models.PasswordResetToken.token == token,
        models.PasswordResetToken.used == False,
        models.PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if not reset_token:
        # Token invalid, expired, or already used
        return templates.TemplateResponse("reset-password.html", {
            "request": request,
            "token": token,
            "error": "Invalid or expired reset token"
        })
    
    return templates.TemplateResponse("reset-password.html", {
        "request": request,
        "token": token
    })

@app.post("/api/auth/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(auth.get_db)):
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
    
    # Update password locally
    user = db.query(models.User).filter(models.User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    user.hashed_password = auth.get_password_hash(request.password)
    
    # Mark token as used
    reset_token.used = True
    db.commit()
    
    return JSONResponse({
        "message": "Password reset successfully. Please login with your new password."
    })

# Helper function for session cleanup (moved before route definition)
def perform_session_cleanup(session_id: str, db: Session):
    """Helper to cleanup session artifacts and DB records (Child records only)"""
    try:
        # Manual Cascade Delete
        db.query(models.StaticAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.DynamicAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.UnifiedAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.VisualAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.H1AuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.PhoneAuditResult).filter_by(session_id=session_id).delete(synchronize_session=False)
    except Exception as e:
        print(f"Cleanup Error DB {session_id}: {e}")
        # Ensure we don't rollback here, allow caller to handle transaction
        # But querying and deleting in same transaction reference is fine.

    # Clean up Files (Best effort)
    folders = [
        f"screenshots/{session_id}",
        f"videos/{session_id}",
        f"diffs/{session_id}"
    ]
    for folder in folders:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except Exception as e:
                print(f"Error deleting folder {folder}: {e}")

@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Delete audit session and associated data"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         raise HTTPException(status_code=401, detail="Not authenticated")
         
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    try:
        perform_session_cleanup(session_id, db)
        
        # Delete Session
        db.delete(session)
        db.commit()
        
        return JSONResponse({"message": "Session deleted"})
        
    except Exception as e:
        db.rollback()
        print(f"Delete Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete session: {str(e)}")

@app.delete("/api/sessions")
async def clear_all_sessions(request: Request, db: Session = Depends(auth.get_db)):
    """Delete ALL audit sessions for the user"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
         raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get all sessions
    sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).all()
    count = len(sessions)
    deleted = 0
    
    for session in sessions:
        try:
            perform_session_cleanup(session.session_id, db)
            db.delete(session)
            db.commit()
            deleted += 1
        except Exception as e:
            db.rollback()
            print(f"Failed to clear session {session.session_id}: {e}")
            
    return JSONResponse({"message": f"History cleared. Deleted {deleted}/{count} sessions."})

@app.post("/upload/static")
async def upload_static(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Responsive Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for static audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])

    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)

    if not selected_browsers or not selected_resolutions:
        return JSONResponse({"error": "Select at least one browser and resolution"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_expected = len(urls) * len(selected_browsers) * len(selected_resolutions)
    
    token = request.cookies.get("access_token")

    # Start background task
    background_tasks.add_task(static_audit_task, urls, selected_browsers, selected_resolutions, session_id, user.id, session_name, token)
    
    # Store task reference
    running_tasks[session_id] = "static"

    return JSONResponse({
        "session": session_id,
        "total_expected": total_expected,
        "type": "static"
    })

@app.post("/upload/dynamic")
async def upload_dynamic(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Dynamic Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for dynamic audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])

    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)

    supported_browsers = [b for b in selected_browsers if b in ["Chrome", "Edge"]]
    if not supported_browsers:
        return JSONResponse({"error": "Select Chrome or Edge for video recording"}, status_code=400)

    if not selected_resolutions:
        return JSONResponse({"error": "Select at least one resolution"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_expected = len(urls) * len(supported_browsers) * len(selected_resolutions)
    
    token = request.cookies.get("access_token")

    # Start background task
    background_tasks.add_task(dynamic_audit_task, urls, supported_browsers, selected_resolutions, session_id, user.id, session_name, token)
    
    # Store task reference
    running_tasks[session_id] = "dynamic"

    return JSONResponse({
        "session": session_id,
        "total_expected": total_expected,
        "type": "dynamic"
    })

@app.post("/upload/h1")
async def upload_h1(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    session_name: str = Form("My H1 Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for H1 audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
        
    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Start background task
    background_tasks.add_task(h1_audit_task, urls, session_id, user.id, session_name)
    
    # Store task reference
    running_tasks[session_id] = "h1"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "h1"
    })

@app.post("/upload/phone")
async def upload_phone(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    target_numbers: Optional[str] = Form(None),
    options: str = Form("[]"),
    session_name: str = Form("My Phone Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(auth.get_db)
):
    """Upload URLs for phone audit - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])

    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    target_numbers_list = []
    if target_numbers:
        target_numbers_list = [n.strip() for n in target_numbers.splitlines() if n.strip()]

    selected_options = json.loads(options)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create session record first
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="phone",
        name=session_name,
        urls=json.dumps(urls),
        browsers=json.dumps([]),
        resolutions=json.dumps([]),
        total_expected=len(urls),
        status="running"
    )
    db.add(new_session)
    db.commit()

    # Start background task
    background_tasks.add_task(phone_audit_task, urls, target_numbers_list, selected_options, session_id, user.id, session_name)
    
    # Store task reference
    running_tasks[session_id] = "phone"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "phone"
    })

@app.post("/api/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Stop a running session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update status
    session.status = "stopped"
    db.commit()
    
    return {"message": "Session stopped successfully"}

@app.delete("/api/sessions/{session_id}")
async def delete_session(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Delete a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Find session
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Delete files
    if session.session_type == "static":
        folder_path = f"screenshots/{session_id}"
    elif session.session_type == "dynamic":
        folder_path = f"videos/{session_id}"
    elif session.session_type == "h1":
        folder_path = f"h1-audits/{session_id}"
    else:
        folder_path = f"phone-audits/{session_id}"
    
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path, ignore_errors=True)
    
    # Delete related audit results
    if session.session_type == "h1":
        results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        for result in results:
            db.delete(result)
    elif session.session_type == "phone":
        results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
        for result in results:
            db.delete(result)
    
    # Delete database record
    db.delete(session)
    db.commit()
    
    return {"message": "Session deleted successfully"}

@app.delete("/api/sessions")
async def delete_all_sessions(
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Delete all completed sessions for user"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    sessions = db.query(models.AuditSession).filter(
        models.AuditSession.user_id == user.id,
        models.AuditSession.status == "completed"
    ).all()
    
    deleted_count = 0
    for session in sessions:
        # Delete files
        if session.session_type == "static":
            folder_path = f"screenshots/{session.session_id}"
        elif session.session_type == "dynamic":
            folder_path = f"videos/{session.session_id}"
        elif session.session_type == "h1":
            folder_path = f"h1-audits/{session.session_id}"
        else:
            folder_path = f"phone-audits/{session.session_id}"
        
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path, ignore_errors=True)
            
        # Delete related results
        if session.session_type == "h1":
            try:
                db.query(models.H1AuditResult).filter_by(session_id=session.session_id).delete()
            except: pass
        elif session.session_type == "phone":
             try:
                db.query(models.PhoneAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass
        elif session.session_type == "unified":
             try:
                db.query(models.UnifiedAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass
        elif session.session_type == "accessibility":
             try:
                db.query(models.AccessibilityAuditResult).filter_by(session_id=session.session_id).delete()
             except: pass

        db.delete(session)
        deleted_count += 1
        
    db.commit()
    return {"message": f"Deleted {deleted_count} sessions"}

@app.get("/progress/{session_type}/{session_id}")
async def progress(session_type: str, session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/static/{session_id}")
async def static_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a static session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/dynamic/{session_id}")
async def dynamic_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a dynamic session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/h1/{session_id}")
async def h1_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a H1 audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/progress/phone/{session_id}")
async def phone_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a phone audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/results/{session_type}/{session_id}")
async def view_results(session_type: str, session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """View results of a completed session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check if session is completed
    if session.status != "completed":
        raise HTTPException(status_code=400, detail="Session not completed yet")
    
    # Parse session data
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except:
        session.urls = []
        session.browsers = []
        session.resolutions = []
    
    # Render appropriate results template
    if session_type == "static":
        results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
        return templates.TemplateResponse("static_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "static",
            "results": results
        })
    elif session_type == "dynamic":
        # Filter browsers to only include Chrome and Edge for dynamic audits
        session.browsers = [b for b in session.browsers if b in ["Chrome", "Edge"]]
        return templates.TemplateResponse("performance_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "dynamic"
        })
    elif session_type == "h1":
        # Get H1 audit results
        h1_results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        
        # Convert results to dict format
        results_data = []
        for result in h1_results:
            results_data.append({
                "url": result.url,
                "h1_count": result.h1_count,
                "h1_texts": result.h1_texts,
                "issues": result.issues
            })
        
        return templates.TemplateResponse("h1_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "session_type": "h1",
            "results": results_data
        })
    elif session_type == "phone":
        results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
        return templates.TemplateResponse("phone_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "results": results
        })
    elif session_type == "performance":
        results = db.query(models.PerformanceAuditResult).join(
            models.AuditSession, models.PerformanceAuditResult.session_id == models.AuditSession.session_id
        ).filter(
            models.PerformanceAuditResult.session_id == session_id
        ).all()
        return templates.TemplateResponse("performance_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "results": results
        })
    elif session_type == "accessibility":
         results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
         return templates.TemplateResponse("accessibility_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "results": results
        })
    elif session_type == "meta-tags":
        results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
        return templates.TemplateResponse("meta_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "results": results
        })
    elif session_type == "sitemap":
        results = db.query(models.SitemapResult).filter_by(session_id=session_id).all()
        return templates.TemplateResponse("sitemap_report.html", {
            "request": request,
            "user": user,
            "session": session,
            "session_id": session_id,
            "results": results
        })
    else:
        raise HTTPException(status_code=400, detail="Invalid session type")

@app.get("/results/accessibility/detail/{result_id}")
async def view_accessibility_detail(result_id: int, request: Request, db: Session = Depends(auth.get_db)):
    """View detailed accessibility results for a single URL"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    result = db.query(models.AccessibilityAuditResult).filter_by(id=result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
        
    session = db.query(models.AuditSession).filter_by(session_id=result.session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=403, detail="Access denied")
        
    try:
        report_data = json.loads(result.report_json)
    except:
        report_data = []
        
    return templates.TemplateResponse("accessibility_detail.html", {
        "request": request,
        "user": user,
        "session": session,
        "result": result,
        "violations": report_data
    })

@app.get("/results/static/{session_id}/snapshots")
async def static_snapshots_view(session_id: str, url: str, browser: str, request: Request, db: Session = Depends(auth.get_db)):
    """View detailed snapshots for a specific URL and browser - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Parse session data (same as view_results)
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except:
        session.urls = []
        session.browsers = []
        session.resolutions = []
        
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id, url=url, browser=browser).all()
    
    # Get all URLs in this session for navigation
    all_results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    urls = list(dict.fromkeys([r.url for r in all_results]))
    
    current_index = urls.index(url) if url in urls else 0
    prev_url = urls[current_index - 1] if current_index > 0 else None
    next_url = urls[current_index + 1] if current_index < len(urls) - 1 else None
    
    return templates.TemplateResponse("static_snapshots.html", {
        "request": request,
        "user": user,
        "session": session,
        "results": results,
        "target_url": url,
        "current_browser": browser,
        "prev_url": prev_url,
        "next_url": next_url,
        "session_id": session_id
    })

@app.get("/progress/performance/{session_id}")
async def performance_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a performance audit session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/h1-results/{session_id}")
async def get_h1_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get H1 audit results for a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get results
    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    
    # Convert to list of dicts
    results_data = []
    for result in results:
        try:
            h1_texts = json.loads(result.h1_texts) if result.h1_texts else []
            issues = json.loads(result.issues) if result.issues else []
        except:
            h1_texts = []
            issues = []
            
        results_data.append({
            "url": result.url,
            "h1_count": result.h1_count,
            "h1_texts": h1_texts,
            "issues": issues,
            "created_at": result.created_at.isoformat() if result.created_at else None
        })
    
    return JSONResponse(results_data)

@app.get("/phone-results/{session_id}")
async def get_phone_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get phone audit results for a session - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Verify ownership
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get results
    results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
    
    # Convert to list of dicts
    results_data = []
    for result in results:
        try:
            phone_numbers = json.loads(result.phone_numbers) if result.phone_numbers else []
            formats_detected = json.loads(result.formats_detected) if result.formats_detected else []
            issues = json.loads(result.issues) if result.issues else []
        except:
            phone_numbers = []
            formats_detected = []
            issues = []
            
        results_data.append({
            "url": result.url,
            "phone_count": result.phone_count,
            "phone_numbers": phone_numbers,
            "formats_detected": formats_detected,
            "issues": issues,
            "created_at": result.created_at.isoformat() if result.created_at else None
        })
    
    return JSONResponse(results_data)

@app.get("/check-files/{session_type}/{session_id}")
async def check_files(session_type: str, session_id: str, browser: str, url: str):
    """Check if files exist for a specific URL and browser"""
    try:
        unique = get_unique_filename(url)
        
        if session_type == "static":
            # Check for screenshots
            files_exist = []
            resolutions = ["1920x1080", "1366x768", "1280x720", "1024x768", "768x1024", "480x800"]
            
            for res in resolutions:
                file_path = f"screenshots/{session_id}/{browser}/{unique}__{res}.png"
                if os.path.exists(file_path):
                    files_exist.append(res)
            
            return {"files_exist": files_exist, "total_checked": len(resolutions)}
        elif session_type == "dynamic":
            # Check for videos
            files_exist = []
            resolutions = ["1920x1080", "1366x768", "1280x720", "1024x768", "768x1024", "480x800"]
            
            for res in resolutions:
                file_path = f"videos/{session_id}/{browser}/{unique}__{res}.mp4"
                if os.path.exists(file_path):
                    files_exist.append(res)
            
            return {"files_exist": files_exist, "total_checked": len(resolutions)}
        else:
            return {"files_exist": [], "total_checked": 0}
    except Exception as e:
        return {"error": str(e), "files_exist": [], "total_checked": 0}

# ========== STREAMING RESPONSE FOR VIDEOS ==========

@app.get("/videos/{session_id}/{browser}/{video_file}")
async def stream_video(session_id: str, browser: str, video_file: str, request: Request):
    """Stream video files for dynamic results"""
    video_path = f"videos/{session_id}/{browser}/{video_file}"
    
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video not found")
    
    file_size = os.path.getsize(video_path)
    range_header = request.headers.get("Range")
    
    if range_header:
        # Parse Range header
        start_str, end_str = range_header.replace("bytes=", "").split("-")
        start = int(start_str)
        end = int(end_str) if end_str else file_size - 1
        
        if start >= file_size:
            raise HTTPException(status_code=416, detail="Range not satisfiable")
        
        end = min(end, file_size - 1)
        length = end - start + 1
        
        with open(video_path, "rb") as video:
            video.seek(start)
            data = video.read(length)
        
        response = StreamingResponse(
            iter([data]),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Disposition": f"inline; filename={video_file}"
            }
        )
        return response
    else:
        # Return full file
        file_like = open(video_path, mode="rb")
        return StreamingResponse(
            file_like,
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
                "Content-Disposition": f"inline; filename={video_file}"
            }
        )

# ========== VISUAL REGRESSION FUNCTIONS ==========

async def compare_images_logic(base_url: str, compare_url: str, session_id: str, db: Session):
    session_folder = f"diffs/{session_id}"
    os.makedirs(session_folder, exist_ok=True)
    
    extraction_script = """
    () => {
        const elements = [];
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
        while (walker.nextNode()) {
            const node = walker.currentNode;
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            
            if (rect.width === 0 || rect.height === 0 || style.display === 'none' || style.visibility === 'hidden') continue;
            
            const hasText = Array.from(node.childNodes).some(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim().length > 0);
            
            if (hasText || node.tagName === 'IMG' || node.tagName === 'BUTTON' || node.tagName === 'INPUT') {
                elements.push({
                    tag: node.tagName,
                    id: node.id,
                    classes: [...node.classList],
                    text: node.innerText?.trim().substring(0, 200) || "",
                    rect: {
                        x: rect.x + window.scrollX,
                        y: rect.y + window.scrollY,
                        width: rect.width,
                        height: rect.height
                    },
                    styles: {
                        'color': style.color,
                        'background-color': style.backgroundColor,
                        'font-family': style.fontFamily,
                        'font-size': style.fontSize,
                        'font-weight': style.fontWeight,
                        'text-align': style.textAlign
                    }
                });
            }
        }
        return elements;
    }
    """
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()
            
            # Capture Base
            await page.goto(base_url, wait_until="networkidle", timeout=60000)
            base_path = f"{session_folder}/base.png"
            await page.screenshot(path=base_path, full_page=True)
            base_dom = await page.evaluate(extraction_script)
            
            # Capture Compare
            await page.goto(compare_url, wait_until="networkidle", timeout=60000)
            compare_path = f"{session_folder}/compare.png"
            await page.screenshot(path=compare_path, full_page=True)
            compare_dom = await page.evaluate(extraction_script)
            
            await browser.close()
            
            # Calculate DOM Diff
            try:
                dom_diffs = dom_diff.compare_dom_elements(base_dom, compare_dom)
                with open(f"{session_folder}/diff_report.json", "w") as f:
                    json.dump(dom_diffs, f)
            except Exception as e:
                print(f"DOM Diff Error: {e}")

            # Compare logic (Pixel Diff)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, process_image_diff, base_path, compare_path, session_folder, session_id, base_url, compare_url)

    except Exception as e:
        print(f"Visual Audit Error: {e}")
        pass

def process_image_diff(base_path, compare_path, session_folder, session_id, base_url, compare_url):
    # This runs in a thread
    import database
    from sqlalchemy.orm import Session
    
    # Create new db session for thread
    db = database.SessionLocal()
    
    try:
        img1 = Image.open(base_path).convert("RGB")
        img2 = Image.open(compare_path).convert("RGB")
        
        # Resize to match smallest dimensions to avoid errors
        width = min(img1.width, img2.width)
        height = min(img1.height, img2.height)
        
        img1 = img1.resize((width, height))
        img2 = img2.resize((width, height))
        
        diff_img = Image.new("RGB", (width, height))
        diff_pixels = diff_img.load()
        
        pixels1 = img1.load()
        pixels2 = img2.load()
        
        diff_count = 0
        total_pixels = width * height
        
        for y in range(height):
            for x in range(width):
                r1, g1, b1 = pixels1[x, y]
                r2, g2, b2 = pixels2[x, y]
                
                diff = abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
                if diff > 15: # Threshold
                    diff_pixels[x, y] = (255, 0, 0) # Highlight Red
                    diff_count += 1
                else:
                    # Fade out slightly
                    diff_pixels[x, y] = (int(r1*0.3), int(g1*0.3), int(b1*0.3))
        
        diff_path = f"{session_folder}/diff.png"
        diff_img.save(diff_path)
        
        diff_score = int((diff_count / total_pixels) * 100)
        
        # Save Result
        result = models.VisualAuditResult(
            session_id=session_id,
            base_url=base_url,
            compare_url=compare_url,
            diff_score=diff_score,
            base_image_path=base_path,
            compare_image_path=compare_path,
            diff_image_path=diff_path
        )
        db.add(result)
        
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "completed"
            session.completed = 1
            session.completed_at = datetime.utcnow()
            db.commit()
            
    except Exception as e:
        print(f"Diff processing error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()

# ========== ACCESSIBILITY AUDIT FUNCTIONS ==========




# ========== META TAGS AUDIT FUNCTIONS ==========

async def audit_meta_tags_logic(urls: List[str], session_id: str):
    db = database.SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        completed = 0
        
        async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=30.0) as client:
            for url in urls:
                try:
                    resp = await client.get(url)
                    html = resp.text
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract Data
                    title = soup.title.string.strip() if soup.title else None
                    
                    desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', attrs={'property': 'description'})
                    description = desc_tag['content'].strip() if desc_tag and desc_tag.get('content') else None
                    
                    keywords_tag = soup.find('meta', attrs={'name': 'keywords'})
                    keywords = keywords_tag['content'].strip() if keywords_tag and keywords_tag.get('content') else None
                    
                    canonical_tag = soup.find('link', attrs={'rel': 'canonical'})
                    canonical = canonical_tag['href'].strip() if canonical_tag and canonical_tag.get('href') else None
                    
                    # OG Tags
                    og_tags = {}
                    for meta in soup.find_all('meta', property=re.compile(r'^og:')):
                        if meta.get('property') and meta.get('content'):
                            # Handle og:image special case (sometimes multiple) - strictly simple here
                            prop_name = meta['property'].split(':', 1)[1]
                            og_tags[prop_name] = meta['content']
                            
                    # Capture article:published_time specifically into og_tags for report
                    article_published = soup.find('meta', property='article:published_time')
                    if article_published and article_published.get('content'):
                        og_tags['article:published_time'] = article_published['content']

                    # Twitter Cards
                    twitter_tags = {}
                    for meta in soup.find_all('meta', attrs={'name': re.compile(r'^twitter:')}):
                         if meta.get('name') and meta.get('content'):
                            twitter_tags[meta['name'].split(':', 1)[1]] = meta['content']
                         
                    # Schema
                    schema_tags = []
                    for script in soup.find_all('script', type='application/ld+json'):
                        try:
                            if script.string:
                                data = json.loads(script.string)
                                # Extract datePublished if available in schema
                                if isinstance(data, dict):
                                    if 'datePublished' in data:
                                        # Add to og_tags as fallback/primary if not in meta
                                        if 'article:published_time' not in og_tags:
                                            og_tags['article:published_time'] = data['datePublished']
                                    schema_tags.append(json.dumps(data)) # Store as strings
                                elif isinstance(data, list):
                                    for item in data:
                                        if isinstance(item, dict) and 'datePublished' in item:
                                             if 'article:published_time' not in og_tags:
                                                og_tags['article:published_time'] = item['datePublished']
                                    schema_tags.extend([json.dumps(x) for x in data])
                        except: pass
                        
                    # Calculate Score
                    score = 100
                    if not title: score -= 20
                    elif len(title) > 60: score -= 5
                    if not description: score -= 20
                    elif len(description) > 160: score -= 5
                    if not canonical: score -= 10
                    if not og_tags: score -= 10
                    score = max(0, score)
                    
                    result = models.MetaTagsResult(
                        session_id=session_id,
                        url=url,
                        title=title,
                        description=description,
                        keywords=keywords,
                        canonical=canonical,
                        og_tags=json.dumps(og_tags),
                        twitter_tags=json.dumps(twitter_tags),
                        schema_tags=json.dumps(schema_tags),
                        score=score,
                        missing_tags=json.dumps([]),
                        warnings=json.dumps([]),
                        keyword_consistency=json.dumps({})
                    )
                    db.add(result)
                    
                except Exception as e:
                    print(f"Error processing {url}: {e}")
                    # Create empty result to show error?
                    result = models.MetaTagsResult(
                        session_id=session_id,
                        url=url,
                        title="Error",
                        description=f"Failed to scan: {str(e)}",
                        score=0
                    )
                    db.add(result)
                
                completed += 1
                session.completed = completed
                db.commit()
                # Slight delay to avoid rate limits
                await asyncio.sleep(0.5)
                
        session.status = "completed"
        db.commit()
        
    except Exception as e:
        print(f"Meta Audit failed: {e}")
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()



# ========== XML SITEMAP AUDIT FUNCTIONS ==========

import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import httpx
import time

async def audit_sitemap_logic(sitemap_url: str, session_id: str):
    """Refactored Sitemap audit with smarter discovery and robust XML parsing"""
    db = database.SessionLocal()
    from utils.security import is_safe_url
    import time
    from urllib.parse import urlparse
    import xml.etree.ElementTree as ET
    
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return
        
        # Check if sitemap_url is safe
        if not is_safe_url(sitemap_url):
            session.status = "error"
            db.commit()
            return

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=True) as client:
            start_time = time.time()
            try:
                resp = await client.get(sitemap_url)
                load_time_ms = int((time.time() - start_time) * 1000)
                
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}")
                
                # Discovery Logic
                robots_status = "direct"
                if "text/html" in resp.headers.get("content-type", "").lower():
                    parsed = urlparse(sitemap_url)
                    base_url = f"{parsed.scheme}://{parsed.netloc}"
                    try:
                        rob_resp = await client.get(f"{base_url}/robots.txt", timeout=5)
                        sm_match = re.search(r'Sitemap:\s*([^\s]+)', rob_resp.text, re.I)
                        if sm_match:
                            sitemap_url = sm_match.group(1).strip()
                            resp = await client.get(sitemap_url)
                            robots_status = "discovered"
                        else:
                            # Try common paths
                            for path in ["/sitemap.xml", "/sitemap_index.xml"]:
                                test_resp = await client.get(f"{base_url}{path}")
                                if test_resp.status_code == 200:
                                    sitemap_url = f"{base_url}{path}"
                                    resp = test_resp
                                    robots_status = "guessed"
                                    break
                    except: 
                        robots_status = "error"
                
                # Process XML
                try:
                    # Strip namespaces for easier parsing
                    xml_str = re.sub(r' xmlns="[^"]+"', '', resp.text, count=1)
                    root = ET.fromstring(xml_str.encode('utf-8'))
                except Exception as e:
                     raise Exception(f"Invalid XML structure: {str(e)[:50]}")

                tag = root.tag.split('}')[-1]
                is_index = (tag == 'sitemapindex')
                
                urls = []
                for loc in root.findall('.//loc'):
                    if loc.text: urls.append(loc.text.strip())

                count = len(urls)
                
                # Reachability Check (Sample up to 20 URLs)
                reachability_results = {}
                if urls:
                    sample_size = min(20, len(urls))
                    sample_urls = random.sample(urls, sample_size)
                    
                    async def check_url(target_url):
                        # Check if session was stopped
                        db.expire_all()
                        db.refresh(session)
                        if session.status == "stopped":
                            return target_url, 0
                            
                        try:
                            # Use HEAD for efficiency, fallback to GET
                            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as check_client:
                                try:
                                    cr = await check_client.head(target_url)
                                    if cr.status_code == 405: # Method Not Allowed
                                        cr = await check_client.get(target_url)
                                    return target_url, cr.status_code
                                except:
                                    cr = await check_client.get(target_url)
                                    return target_url, cr.status_code
                        except Exception as e:
                            return target_url, 0 # 0 for connection error
                            
                    check_tasks = [check_url(u) for u in sample_urls]
                    results = await asyncio.gather(*check_tasks)
                    reachability_results = dict(results)

                # Simple Score calculation
                score = 50
                if robots_status in ["discovered", "direct"]: score += 20
                if count > 0: score += 10
                if reachability_results:
                    # Calculate success rate from sample
                    success_rate = sum(1 for s in reachability_results.values() if s == 200 or s == "sitemap") / len(reachability_results)
                    score += int(success_rate * 20)
                score = min(100, score)
                
                result = models.SitemapResult(
                    session_id=session_id,
                    url=sitemap_url,
                    is_index=is_index,
                    url_count=count,
                    child_sitemaps=json.dumps(urls if is_index else []),
                    robots_status=robots_status,
                    load_time_ms=load_time_ms,
                    reachability_sample=json.dumps(reachability_results),
                    score=score
                )
                db.add(result)
                
                db.expire_all()
                if session:
                    db.refresh(session)
                    if session.status != "stopped":
                        session.status = "completed"
                        session.completed = 1
                        session.completed_at = datetime.utcnow()
                        db.commit()
                    else:
                         print(f"[SITEMAP] Session {session_id} ended with STOPPED status.")

            except Exception as e:
                print(f"Sitemap Error: {e}")
                session.status = "error"
                db.commit()
    except Exception as fatal:
        print(f"Sitemap Fatal: {fatal}")
    finally:
        db.close()


# ========== NEW ROUTES ==========

@app.get("/platform/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    """Serve the dynamic dashboard page"""
    
    # 1. Stats
    running_audits = db.query(models.AuditSession).filter(models.AuditSession.status == "running", models.AuditSession.user_id == user.id).count()
    audits_completed = db.query(models.AuditSession).filter(models.AuditSession.status == "completed", models.AuditSession.user_id == user.id).count()
    
    # Calculate URLs tested
    urls_tested_result = db.query(func.sum(models.AuditSession.total_expected)).filter(models.AuditSession.status == "completed", models.AuditSession.user_id == user.id).scalar()
    urls_tested = int(urls_tested_result) if urls_tested_result else 0
    
    # Critical Findings
    critical_findings_result = db.query(func.sum(models.AccessibilityAuditResult.critical_count))\
        .join(models.AuditSession, models.AuditSession.session_id == models.AccessibilityAuditResult.session_id)\
        .filter(models.AuditSession.user_id == user.id).scalar()
    critical_findings = int(critical_findings_result) if critical_findings_result else 0

    # 2. Recent Activity - Formatted
    recent_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).order_by(desc(models.AuditSession.created_at)).limit(10).all()
    
    activity_log = []
    for audit in recent_audits:
        # Determine URL Count
        url_count = 0
        try:
            urls = json.loads(audit.urls) if isinstance(audit.urls, str) else audit.urls
            if urls:
                url_count = len(urls)
        except:
            url_count = 0
            
        # Format Date: DD/MM/YY, HH:MM am/pm
        formatted_date = audit.created_at.strftime("%d-%m-%y, %I:%M %p").lower()

        # Map session types to display names
        type_map = {
            "static": "Responsive Audit",
            "performance": "Speed Test",
            "phone": "CTA Audit",
            "h1": "H1 Tags",
            "metatags": "Meta Tags",
            "sitemap": "XML Sitemaps",
            "accessibility": "Accessibility"
        }
        display_type = type_map.get(audit.session_type, audit.session_type.replace("-", " ").title())

        activity_log.append({
            "session_id": audit.session_id,
            "name": audit.name or f"{display_type} Audit",
            "type": display_type,
            "status": audit.status.title(), # Capitalize for display
            "url_count": url_count,
            "date": formatted_date,
            "completed": audit.completed,
            "total": audit.total_expected
        })

    # 3. Graph Data (Last 7 Days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    
    # Accessibility
    acc_results = db.query(models.AccessibilityAuditResult)\
        .join(models.AuditSession, models.AuditSession.session_id == models.AccessibilityAuditResult.session_id)\
        .filter(models.AuditSession.user_id == user.id, models.AccessibilityAuditResult.created_at >= seven_days_ago).all()
    acc_exceeds = sum(r.critical_count + r.serious_count for r in acc_results)
    acc_within = sum(r.moderate_count + r.minor_count for r in acc_results)
    acc_total = acc_exceeds + acc_within
    
    # Performance
    perf_results = db.query(models.PerformanceAuditResult)\
        .join(models.AuditSession, models.AuditSession.session_id == models.PerformanceAuditResult.session_id)\
        .filter(models.AuditSession.user_id == user.id, models.PerformanceAuditResult.created_at >= seven_days_ago).all()
    perf_exceeds = sum(1 for r in perf_results if r.score < 50)
    perf_within = sum(1 for r in perf_results if 50 <= r.score < 90)
    perf_total = perf_exceeds + perf_within
    
    # Phone
    phone_results = db.query(models.PhoneAuditResult)\
        .join(models.AuditSession, models.AuditSession.session_id == models.PhoneAuditResult.session_id)\
        .filter(models.AuditSession.user_id == user.id, models.PhoneAuditResult.created_at >= seven_days_ago).all()
    phone_total_issues = 0
    for r in phone_results:
        try:
            issues = json.loads(r.issues)
            phone_total_issues += len(issues)
        except: pass
    phone_exceeds = 0 
    phone_within = phone_total_issues
    phone_total = phone_total_issues

    # H1
    h1_results = db.query(models.H1AuditResult)\
        .join(models.AuditSession, models.AuditSession.session_id == models.H1AuditResult.session_id)\
        .filter(models.AuditSession.user_id == user.id, models.H1AuditResult.created_at >= seven_days_ago).all()
    h1_total_issues = 0
    for r in h1_results:
        try:
            issues = json.loads(r.issues)
            h1_total_issues += len(issues)
        except: pass
    h1_exceeds = 0
    h1_within = h1_total_issues
    h1_total = h1_total_issues
    
    max_val = max(acc_total, perf_total, phone_total, h1_total, 10)
    
    def get_pct(val, maximum):
        return (val / maximum) * 85
        
    graph_data = {
        "acc": {"within": get_pct(acc_within, max_val), "exceeds": get_pct(acc_exceeds, max_val), "total": acc_total},
        "perf": {"within": get_pct(perf_within, max_val), "exceeds": get_pct(perf_exceeds, max_val), "total": perf_total},
        "phone": {"within": get_pct(phone_within, max_val), "exceeds": get_pct(phone_exceeds, max_val), "total": phone_total},
        "h1": {"within": get_pct(h1_within, max_val), "exceeds": get_pct(h1_exceeds, max_val), "total": h1_total},
        "max_scale": max_val
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "show_nav": True,
        "running_audits": running_audits,
        "audits_completed": audits_completed,
        "urls_tested": urls_tested,
        "critical_findings": critical_findings,
        "recent_activity": activity_log,
        "graph": graph_data
    })



@app.get("/platform/device-lab", response_class=HTMLResponse)
async def device_lab_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("device_lab.html", {"request": request, "user": user})

@app.get("/scan/xml-sitemaps", response_class=HTMLResponse)
async def xml_sitemaps_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("sitemaps.html", {"request": request, "user": user})


@app.get("/platform/visual", response_class=HTMLResponse)
async def visual_test_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("visual_regression.html", {"request": request, "user": user})

@app.get("/platform/profile", response_class=HTMLResponse)
async def profile_view(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Fetch simple stats for profile
    # print(f"DEBUG: Profile request for user {user.username} (ID: {user.id})")
    
    with open("debug_log.txt", "a") as f:
        f.write(f"\nTime: {datetime.datetime.now()}\n")
        f.write(f"User: {user.username}, ID: {user.id}, Type: {type(user.id)}\n")
    
    total_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).count()
    
    with open("debug_log.txt", "a") as f:
        f.write(f"User Count: {total_sessions}\n")
    
    # print(f"DEBUG: User-specific sessions count: {total_sessions}")
    
    # Check total DB count for comparison
    total_db = db.query(models.AuditSession).count()
    
    with open("debug_log.txt", "a") as f:
        f.write(f"Total DB: {total_db}\n")
    
    # print(f"DEBUG: Total DB count: {total_db}")
    
    completed_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "completed").count()
    
    return templates.TemplateResponse("profile.html", {
        "request": request, 
        "user": user,
        "stats": {
            "total_sessions": total_sessions,
            "completed_audits": completed_audits,
            "success_rate": int((completed_audits / total_sessions * 100)) if total_sessions > 0 else 0
        }
    })

@app.get("/profile")
async def profile_redirect():
    return RedirectResponse(url="/platform/profile")

@app.get("/responsive", response_class=HTMLResponse)
async def responsive_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("static_snapshots.html", {"request": request, "user": user})

@app.get("/responsive/dynamic", response_class=HTMLResponse)
async def dynamic_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/h1-audit", response_class=HTMLResponse)
async def h1_audit_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("h1_tags.html", {"request": request, "user": user})

@app.get("/phone-audit", response_class=HTMLResponse)
async def phone_audit_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("phone_validator.html", {"request": request, "user": user})

@app.get("/login", response_class=HTMLResponse)
async def login_view(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_view(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_view(request: Request):
    return templates.TemplateResponse("forgot-password.html", {"request": request})

@app.get("/platform/performance", response_class=HTMLResponse)
async def performance_test_view(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    # Fetch recent performance audit results for this user
    recent_results = db.query(models.PerformanceAuditResult).join(
        models.AuditSession, models.PerformanceAuditResult.session_id == models.AuditSession.session_id
    ).filter(
        models.AuditSession.user_id == user.id
    ).order_by(models.PerformanceAuditResult.id.desc()).limit(10).all()
    
    return templates.TemplateResponse("performance_audit.html", {
        "request": request, 
        "user": user,
        "recent_results": recent_results
    })

@app.post("/api/visual-test")
async def trigger_visual_test(
    background_tasks: BackgroundTasks, 
    base_url: str = Form(...), 
    compare_url: str = Form(...), 
    user: models.User = Depends(require_auth), 
    db: Session = Depends(auth.get_db)
):
    session_id = f"vis_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="visual",
        name=f"Visual: {get_unique_filename(base_url)}",
        urls=json.dumps([base_url, compare_url]),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["1280x800"]),
        total_expected=1
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(compare_images_logic, base_url, compare_url, session_id, db)
    
    return JSONResponse({
        "status": "started",
        "session_id": session_id,
        "message": "Visual audit started"
    })

@app.post("/upload/performance")
async def upload_performance(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    strategy: str = Form("desktop"),
    session_name: str = Form("My Performance Audit"),
    db: Session = Depends(auth.get_db)
):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    urls = []
    
    # Process File
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
        
    # Process Manual Entry
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="performance",
        name=session_name,
        urls=json.dumps(urls),
        browsers=json.dumps([strategy]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(urls)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_performance_task, urls, session_id, strategy)
    
    # Store task reference
    running_tasks[session_id] = "performance"

    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "performance"
    })

@app.get("/api/results/{session_id}")
async def get_any_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Generic results endpoint"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    if session.session_type == "visual":
         results = db.query(models.VisualAuditResult).filter_by(session_id=session_id).all()
         response_data = {
             "results": [{"score": r.diff_score, "diff_img": r.diff_image_path} for r in results],
             "dom_diffs": []
         }
         
         # Try to load DOM diff report
         diff_report_path = f"diffs/{session_id}/diff_report.json"
         if os.path.exists(diff_report_path):
             try:
                 with open(diff_report_path, "r") as f:
                     response_data["dom_diffs"] = json.load(f)
             except:
                 pass
                 
         return response_data
         
    elif session.session_type == "performance":
         results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
         return [{
             "url": r.url,
             "device_preset": r.device_preset,
             "created_at": r.created_at,
             "ttfb": r.ttfb,
             "fcp": r.fcp,
             "score": r.score,
             "page_load": r.page_load
         } for r in results]
         
    elif session.session_type == "accessibility":
        results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
        return [{
            "url": r.url,
            "score": r.score,
            "violations_count": r.violations_count,
            "critical": r.critical_count,
            "serious": r.serious_count,
            "moderate": r.moderate_count,
            "minor": r.minor_count,
            "violations": json.loads(r.report_json) if r.report_json else []
        } for r in results]
    return []

@app.get("/api/export/{audit_type}/{session_id}")
async def export_audit_results(audit_type: str, session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Export audit results as CSV"""
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    output = io.StringIO()
    writer = csv.writer(output)
    filename = f"{audit_type}_export_{session_id}.csv"
    
    if audit_type == "sitemap":
        writer.writerow(["URL", "Is Index", "URL Count", "Robots Status", "Load Time (ms)", "Score"])
        results = db.query(models.SitemapResult).filter_by(session_id=session_id).all()
        for r in results:
            writer.writerow([r.url, r.is_index, r.url_count, r.robots_status, r.load_time_ms, r.score])
            
    elif audit_type == "h1":
        writer.writerow(["URL", "H1 Count", "H1 Texts", "Issues"])
        results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        for r in results:
            h1s = ", ".join(json.loads(r.h1_texts)) if r.h1_texts else ""
            issues = ", ".join(json.loads(r.issues)) if r.issues else ""
            writer.writerow([r.url, r.h1_count, h1s, issues])
            
    elif audit_type == "meta-tags":
        writer.writerow(["URL", "Title", "Description", "Keywords", "Canonical", "Score"])
        results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
        for r in results:
            writer.writerow([r.url, r.title, r.description, r.keywords, r.canonical, r.score])
            
    elif audit_type == "phone":
        writer.writerow(["URL", "Phone Count", "Phone Numbers", "Formats Detected", "Issues"])
        results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
        for r in results:
            # phone_numbers is a list of dicts with keys: type, number, is_target, valid, source_text
            phone_data = json.loads(r.phone_numbers) if r.phone_numbers else []
            nums = ", ".join([item.get("number", "") for item in phone_data if isinstance(item, dict)])
            
            formats = ", ".join(json.loads(r.formats_detected)) if r.formats_detected else ""
            issues = ", ".join(json.loads(r.issues)) if r.issues else ""
            writer.writerow([r.url, r.phone_count, nums, formats, issues])
            
    elif audit_type == "performance":
        writer.writerow(["URL", "Device", "TTFB (ms)", "FCP (ms)", "DOM Load (ms)", "Page Load (ms)", "Resource Count", "Score"])
        results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
        for r in results:
            writer.writerow([r.url, r.device_preset, r.ttfb, r.fcp, r.dom_load, r.page_load, r.resource_count, r.score])
            
    elif audit_type == "accessibility":
        writer.writerow(["URL", "Score", "Critical", "Serious", "Moderate", "Minor", "Total Violations"])
        results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
        for r in results:
            writer.writerow([r.url, r.score, r.critical_count, r.serious_count, r.moderate_count, r.minor_count, r.violations_count])
    else:
        raise HTTPException(status_code=400, detail="Invalid audit type for export")

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
    return []

@app.delete("/api/audit/{session_id}")
async def delete_audit_session(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Delete an audit session and all its associated results from the database"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the session to verify it belongs to the user
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this session")
    
    # Delete all associated results based on session type
    session_type = session.session_type.lower()
    
    try:
        if session_type == "static":
            db.query(models.StaticAuditResult).filter_by(session_id=session_id).delete()
        elif session_type == "sitemap":
            db.query(models.SitemapResult).filter_by(session_id=session_id).delete()
        elif session_type == "h1":
            db.query(models.H1AuditResult).filter_by(session_id=session_id).delete()
        elif session_type == "meta-tags":
            db.query(models.MetaTagsResult).filter_by(session_id=session_id).delete()
        elif session_type == "phone":
            db.query(models.PhoneAuditResult).filter_by(session_id=session_id).delete()
        elif session_type == "performance":
            db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).delete()
        elif session_type == "accessibility":
            db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).delete()
        
        # Delete the session itself
        db.delete(session)
        db.commit()
        
        return {"message": "Session and all associated results deleted successfully"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting session: {str(e)}")


@app.post("/api/sessions/{session_id}/stop")
async def stop_audit_session(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Stop a running audit session"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Get the session to verify it belongs to the user
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to stop this session")
    
    # Update session status to stopped
    try:
        session.status = 'stopped'
        db.commit()
        return {"message": "Session stopped successfully", "status": "stopped"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error stopping session: {str(e)}")


@app.get("/api/results/meta-tags/{session_id}")
async def get_meta_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
    # If no results and session exists, we might return empty list, handled by frontend
    
    return {"results": [{
        "url": r.url,
        "title": r.title,
        "description": r.description,
        "keywords": r.keywords,
        "canonical": r.canonical,
        "og_tags": json.loads(r.og_tags) if r.og_tags else {},
        "twitter_tags": json.loads(r.twitter_tags) if r.twitter_tags else {},
        "schema_tags": json.loads(r.schema_tags) if r.schema_tags else [],
        "missing_tags": json.loads(r.missing_tags) if r.missing_tags else [],
        "warnings": json.loads(r.warnings) if r.warnings else [],
        "keyword_consistency": json.loads(r.keyword_consistency) if r.keyword_consistency else {},
        "score": r.score
    } for r in results]}

@app.get("/api/results/sitemap/{session_id}")
async def get_sitemap_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    r = db.query(models.SitemapResult).filter_by(session_id=session_id).first()
    if not r: return {"results": {}}
    
    return {"results": {
        "url": r.url,
        "is_index": r.is_index,
        "url_count": r.url_count,
        "child_sitemaps": json.loads(r.child_sitemaps) if r.child_sitemaps else [],
        "robots_status": r.robots_status,
        "load_time_ms": r.load_time_ms,
        "score": r.score,
        "errors": json.loads(r.errors) if r.errors else [],
        "warnings": json.loads(r.warnings) if r.warnings else [],
        "reachability_sample": json.loads(r.reachability_sample) if r.reachability_sample else {}
    }}

@app.get("/api/results/h1/{session_id}")
async def get_h1_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    return [{"url": r.url, "h1_count": r.h1_count, "h1_texts": json.loads(r.h1_texts) if r.h1_texts else [], "issues": json.loads(r.issues) if r.issues else []} for r in results]

@app.get("/progress/h1/{session_id}")
async def h1_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a H1 session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/session-config/static/{session_id}")
async def get_static_session_config(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get static audit session configuration and results with actual file URLs"""
    print(f"[ENTRY] get_static_session_config called for session: {session_id}", flush=True)
    
    user = await get_current_user_from_cookie(request, db)
    print(f"[AUTH] User authenticated: {user is not None}", flush=True)
    if not user:
        raise HTTPException(status_code=401)
    
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    print(f"[DB] Session found: {session is not None}", flush=True)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get all results with actual file paths
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    print(f"[DB] Found {len(results)} StaticAuditResult records", flush=True)
    
    # Parse session data
    urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
    browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
    resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
    print(f"[PARSE] URLs: {len(urls)}, Browsers: {len(browsers)}, Resolutions: {len(resolutions)}", flush=True)
    
    # Build response with actual file URLs from database
    results_map = {}
    for result in results:
        key = f"{result.url}_{result.browser}_{result.resolution}"
        results_map[key] = {
            "url": result.url,
            "browser": result.browser,
            "resolution": result.resolution,
            "screenshot_path": result.screenshot_path,
            "filename": result.filename
        }
    
    print(f"[BUILD] Results map has {len(results_map)} entries", flush=True)
    
    results_list = list(results_map.values()) if results_map else []
    print(f"[BUILD] Results list length: {len(results_list)}", flush=True)
    
    response_data = {
        "urls": urls,
        "browsers": browsers,
        "resolutions": resolutions,
        "results": results_list,
        "type": session.session_type
    }
    
    print(f"[RESPONSE] Keys: {list(response_data.keys())}", flush=True)
    print(f"[RESPONSE] Has results field: {'results' in response_data}", flush=True)
    print(f"[RESPONSE] Results count: {len(response_data.get('results', []))}", flush=True)
    
    # Debug: Print first result if available
    if results_list:
        print(f"[DEBUG] First result filename: {results_list[0].get('filename')}", flush=True)
        print(f"[DEBUG] First result screenshot_path: {results_list[0].get('screenshot_path')}", flush=True)
    
    print(f"[EXIT] Returning response", flush=True)
    
    return response_data


@app.get("/session-config/dynamic/{session_id}")
async def get_dynamic_session_config(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    """Get dynamic audit session configuration and results with actual file URLs"""
    print(f"[ENTRY] get_dynamic_session_config called for session: {session_id}", flush=True)
    
    user = await get_current_user_from_cookie(request, db)
    print(f"[AUTH] User authenticated: {user is not None}", flush=True)
    if not user:
        print("[AUTH] No user - returning 401", flush=True)
        raise HTTPException(status_code=401)
    
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    print(f"[DB] Session found: {session is not None}", flush=True)
    if not session:
        print("[DB] No session - returning 404", flush=True)
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get all results with actual file paths
    results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
    print(f"[DB] Found {len(results)} DynamicAuditResult records", flush=True)
    
    # Parse session data
    urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
    browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
    resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
    print(f"[PARSE] URLs: {len(urls)}, Browsers: {len(browsers)}, Resolutions: {len(resolutions)}", flush=True)
    
    # Build response with actual file URLs from database
    results_map = {}
    for result in results:
        key = f"{result.url}_{result.browser}_{result.resolution}"
        results_map[key] = {
            "url": result.url,
            "browser": result.browser,
            "resolution": result.resolution,
            "video_path": result.video_path,
            "filename": result.filename
        }
    
    print(f"[BUILD] Results map has {len(results_map)} entries", flush=True)
    
    results_list = list(results_map.values()) if results_map else []
    print(f"[BUILD] Results list length: {len(results_list)}", flush=True)
    
    response_data = {
        "urls": urls,
        "browsers": browsers,
        "resolutions": resolutions,
        "results": results_list,
        "type": session.session_type
    }
    
    print(f"[RESPONSE] Keys: {list(response_data.keys())}", flush=True)
    print(f"[RESPONSE] Has results field: {'results' in response_data}", flush=True)
    print(f"[RESPONSE] Results count: {len(response_data.get('results', []))}", flush=True)
    print(f"[EXIT] Returning response", flush=True)
    
    return response_data


@app.get("/test-code-version")
async def test_code_version():
    """Test endpoint to verify code changes are loaded"""
    return {"version": "2024-01-06-v2", "message": "Code changes loaded successfully!", "results_field_added": True}



@app.get("/platform/accessibility", response_class=HTMLResponse)
async def accessibility_test_view(request: Request, user: models.User = Depends(require_auth)):
    return templates.TemplateResponse("accessibility_audit.html", {"request": request, "user": user})

@app.post("/upload/accessibility")
async def upload_accessibility(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    session_name: str = Form("My Accessibility Audit"),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    url_list = []
    
    # Process Manual Entry
    if manual_urls:
         url_list.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])

    # Process File Upload
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        url_list.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate
    url_list = list(dict.fromkeys(url_list))

    if not url_list:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = f"a11y_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="accessibility",
        name=session_name,
        urls=json.dumps(url_list),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(url_list)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_accessibility_task, url_list, session_id)
    
    # Store task reference
    running_tasks[session_id] = "accessibility"
    
    return JSONResponse({
        "session": session_id,
        "total_expected": len(url_list),
        "type": "accessibility"
    })

@app.get("/progress/accessibility/{session_id}")
async def accessibility_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of an accessibility session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }


# ========== META TAGS ROUTES ==========

@app.post("/upload/meta-tags")
async def upload_meta_tags(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    live_url: Optional[str] = Form(None),
    staging_url: Optional[str] = Form(None),
    session_name: str = Form("My Meta Tags Scan"),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    urls = []
    
    # Process Live/Staging comparison
    if live_url and staging_url:
        urls = [live_url.strip(), staging_url.strip()]
        
    # Process File (Fallback or legacy)
    elif file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
        
    # Process Manual Entry (Fallback)
    elif manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    # Deduplicate but preserve order for comparison (Live=0, Staging=1)
    if not (live_url and staging_url):
        urls = list(dict.fromkeys(urls))

    if not urls:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    session_id = f"meta_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="meta-tags",
        name=session_name,
        urls=json.dumps(urls),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(urls)
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_meta_tags_logic, urls, session_id)
    
    # Store task reference
    running_tasks[session_id] = "meta-tags"
    
    return JSONResponse({
        "session": session_id,
        "total_expected": len(urls),
        "type": "meta-tags"
    })

@app.get("/progress/meta-tags/{session_id}")
async def meta_tags_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a meta tags session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@app.get("/api/results/meta-tags/{session_id}")
async def get_meta_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
    
    return {
        "status": session.status,
        "completed": session.completed,
        "total": session.total_expected,
        "results": [{
            "url": r.url,
            "title": r.title,
            "description": r.description,
            "keywords": r.keywords,
            "canonical": r.canonical,
            "score": r.score,
            "og_tags": json.loads(r.og_tags) if r.og_tags else {},
            "twitter_tags": json.loads(r.twitter_tags) if r.twitter_tags else {},
            "schema_tags": json.loads(r.schema_tags) if r.schema_tags else [],
            "missing_tags": json.loads(r.missing_tags) if r.missing_tags else [],
            "warnings": json.loads(r.warnings) if r.warnings else [],
            "keyword_consistency": json.loads(r.keyword_consistency) if r.keyword_consistency else {},
            "created_at": r.created_at
        } for r in results]
    }

@app.get("/scan/meta-tags", response_class=HTMLResponse)
async def meta_tags_page(request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("metatags.html", {"request": request, "user": user})


# ========== XML SITEMAP ROUTES ==========

@app.get("/scan/xml-sitemaps")
async def sitemap_scan_page(request: Request, user = Depends(require_auth)):
    """Sitemap scan page - requires authentication"""
    return templates.TemplateResponse("sitemaps.html", {"request": request, "user": user})

@app.get("/scan/sitemap-history")
async def sitemap_history_page(request: Request, db: Session = Depends(auth.get_db)):
    """Sitemap history page - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    sessions = db.query(models.AuditSession).filter(
        models.AuditSession.user_id == user.id,
        models.AuditSession.session_type == "sitemap"
    ).order_by(models.AuditSession.created_at.desc()).all()
    
    return templates.TemplateResponse("sitemap_history.html", {
        "request": request,
        "user": user,
        "sessions": sessions
    })

@app.post("/upload/sitemap")
async def upload_sitemap(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    session_name: str = Form("My Sitemap Audit"),
    user: models.User = Depends(require_auth),
    db: Session = Depends(auth.get_db)
):
    clean_url = url.strip()
    if not clean_url:
        return JSONResponse({"error": "No URL provided"}, status_code=400)

    session_id = f"sitemap_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="sitemap",
        name=session_name,
        urls=json.dumps([clean_url]),
        browsers=json.dumps(["None"]),
        resolutions=json.dumps(["Default"]),
        total_expected=1
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_sitemap_logic, clean_url, session_id)
    
    # Store task reference
    running_tasks[session_id] = "sitemap"

    return JSONResponse({
        "session": session_id,
        "total_expected": 1,
        "type": "sitemap"
    })

@app.get("/progress/sitemap/{session_id}")
async def sitemap_progress(session_id: str, db: Session = Depends(auth.get_db)):
    """Get progress of a sitemap session"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }


@app.get("/api/results/sitemap/{session_id}")
async def get_sitemap_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.SitemapResult).filter_by(session_id=session_id).first()
    
    res_data = {}
    if results:
        res_data = {
            "url": results.url,
            "is_index": results.is_index,
            "child_sitemaps": json.loads(results.child_sitemaps) if results.child_sitemaps else [],
            "url_count": results.url_count,
            "avg_priority": results.avg_priority,
            "errors": json.loads(results.errors) if results.errors else [],
            "warnings": json.loads(results.warnings) if results.warnings else [],
            "reachability_sample": json.loads(results.reachability_sample) if results.reachability_sample else {},
            "robots_status": results.robots_status,
            "load_time_ms": results.load_time_ms,
            "score": results.score,
            "created_at": results.created_at
        }
    
    return {
        "status": session.status,
        "completed": session.completed,
        "results": res_data
    }

@app.get("/scan/xml-sitemaps", response_class=HTMLResponse)
async def sitemap_page(request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("sitemaps.html", {"request": request, "user": user})

@app.get("/accessibility-results/{session_id}")
async def get_accessibility_results(session_id: str, request: Request, db: Session = Depends(auth.get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404)
        
    results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("audit_history.html", {
        "request": request, 
        "user": user,
        "session": session,
        "results": results
    })


# ========== SESSION CONFIG API ==========

@app.get("/api/session/{session_id}/config")
async def get_session_config(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Get session configuration for restart functionality"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    session = db.query(models.AuditSession).filter_by(
        session_id=session_id,
        user_id=user.id
    ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {
        "session_id": session.session_id,
        "session_type": session.session_type,
        "name": session.name,
        "urls": json.loads(session.urls) if isinstance(session.urls, str) else session.urls,
        "browsers": json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers,
        "resolutions": json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
    }


@app.get("/session-config/static/{session_id}")
async def get_static_session_config(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Get static audit session configuration and results"""
    print(f"[ENTRY] get_static_session_config called for session: {session_id}")
    try:
        # Get user from cookie
        user = await get_current_user_from_cookie(request, db)
        print(f"[AUTH] User authenticated: {user is not None}")
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Get session
        session = db.query(models.AuditSession).filter_by(
            session_id=session_id,
            user_id=user.id
        ).first()
        
        if not session:
            print(f"[ERROR] Session not found: {session_id}")
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Parse URLs
        urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
        browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
        resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
        
        # Get results from database
        results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
        
        results_data = []
        for result in results:
            results_data.append({
                "url": result.url,
                "browser": result.browser,
                "resolution": result.resolution,
                "screenshot_path": result.screenshot_path,
                "filename": result.filename
            })
        
        print(f"[SUCCESS] Returning {len(urls)} URLs and {len(results_data)} results")
        return {
            "urls": urls,
            "browsers": browsers,
            "resolutions": resolutions,
            "results": results_data
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Exception in get_static_session_config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/session-config/dynamic/{session_id}")
async def get_dynamic_session_config(
    session_id: str,
    request: Request,
    db: Session = Depends(auth.get_db)
):
    """Get dynamic audit session configuration and results"""
    try:
        # Get user from cookie
        user = await get_current_user_from_cookie(request, db)
        if not user:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Get session
        session = db.query(models.AuditSession).filter_by(
            session_id=session_id,
            user_id=user.id
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Parse URLs
        urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
        browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
        resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
        
        # Get results from database
        results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
        
        results_data = []
        for result in results:
            results_data.append({
                "url": result.url,
                "browser": result.browser,
                "resolution": result.resolution,
                "video_path": result.video_path,
                "filename": result.filename
            })
        
        return {
            "urls": urls,
            "browsers": browsers,
            "resolutions": resolutions,
            "results": results_data
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error getting dynamic session config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== PERFORMANCE REPORT ROUTE ==========
@app.get("/results/performance/{session_id}", response_class=HTMLResponse)
async def view_performance_results(session_id: str, 
                                 request: Request,
                                 user: models.User = Depends(require_auth), 
                                 db: Session = Depends(auth.get_db)):
    """View performance audit results"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("performance_report.html", {
        "request": request,
        "session_id": session_id,
        "results": results,
        "user": user
    })


@app.get("/api/proxy")
async def proxy_url(url: str):
    """Proxy endpoint to bypass X-Frame-Options with enhanced compatibility and SSRF protection"""
    from utils.security import is_safe_url
    
    if not url.startswith("http"):
        url = "https://" + url

    # SSRF Protection
    if not is_safe_url(url):
        return HTMLResponse(
            content="<div style='color: white; background: #1a1a1a; padding: 20px; font-family: sans-serif;'>"
                    "<h3>Security Block</h3><p>The requested URL is blocked for security reasons (Private/Internal IP).</p></div>",
            status_code=403
        )

    
    
    # Import needed for URL rewriting
    from urllib.parse import urljoin, quote

    async def process_content(content_bytes, final_url, headers):
        """Helper to inject base tag and clean HTML for proxying"""
        content_type = headers.get("content-type", "").lower()
        
        try:
            # --- CASE 1: HTML PROCESSING ---
            if "text/html" in content_type:
                html = content_bytes.decode("utf-8", errors="replace")
                
                import re
                flags = re.IGNORECASE | re.DOTALL

                # 1. Cleanup Security Headers within HTML (Meta tags)
                html = re.sub(r'<meta[^>]*http-equiv=["\']?(Content-Security-Policy|X-Frame-Options)["\']?[^>]*>', '', html, flags=flags)
                html = re.sub(r'\s+(integrity|crossorigin)=["\'][^"\']*["\']', '', html, flags=flags)
                
                # 2. Inject Base Tag & Referrer Policy
                # This ensures all relative assets (images, css, scripts) load from the original source
                base_tag = f'<base href="{final_url}">'
                referrer_tag = '<meta name="referrer" content="no-referrer">'
                injection = f"{base_tag}\n{referrer_tag}"
                
                if "<head" in html.lower():
                    html = re.sub(r'(<head[^>]*>)', f'\\1{injection}', html, count=1, flags=flags)
                elif "<html" in html.lower():
                    html = re.sub(r'(<html[^>]*>)', f'\\1<head>{injection}</head>', html, count=1, flags=flags)
                else:
                    html = f"<head>{injection}</head>" + html

                # 3. AGGRESSIVE SCRIPT SANITIZATION
                # Remove common partial-loading scripts that break when framed or proxied
                bad_patterns = [
                    r'rocket-loader', 
                    r'data-cfasync', 
                    r'litespeed',
                    r'autoptimize',
                    r'wp-emoji'
                ]
                for pat in bad_patterns:
                    html = re.sub(fr'<script[^>]*{pat}[^>]*>.*?</script>', '<!-- Stripped Optimization Script -->', html, flags=flags)
                    html = re.sub(fr'<script[^>]*{pat}[^>]*>', '<!-- Stripped Optimization Script -->', html, flags=flags)

                content_bytes = html.encode("utf-8")
                
                if "charset" not in content_type:
                    headers["content-type"] = "text/html; charset=utf-8"

            # --- CASE 2: CSS PROCESSING ---
            # No longer rewriting CSS urls; letting the browser handle them relative to the doc or valid paths.
            elif "text/css" in content_type:
                 # Ensure charset is set correctly if missing
                 if "charset" not in content_type:
                    headers["content-type"] = "text/css; charset=utf-8"

        except Exception as e:
            print(f"Proxy clean error: {e}")
            
        return content_bytes, headers

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # "Accept-Encoding": "gzip, deflate, br", # Keep removed
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1"
    }

    try:
        # SAFETY: verify=False to handle self-signed or odd cert setups in staging
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            resp = await client.get(url, timeout=20.0, headers=req_headers)
            
            if resp.status_code in [403, 406, 503]: 
                 print(f"Warning: Remote returned {resp.status_code}")

            # EXCLUDE headers
            excluded_headers = [
                'x-frame-options', 'content-security-policy', 'frame-options',
                'content-encoding', 'transfer-encoding', 'content-length',
                'connection', 'strict-transport-security'
                # 'set-cookie' kept allowed
            ]
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
            
            # Ensure UTF-8 intent
            if "text/html" in headers.get("content-type", "").lower() or "text/css" in headers.get("content-type", "").lower():
                 if "charset" not in headers.get("content-type", ""):
                     if "text/css" in headers.get("content-type", ""):
                        headers["content-type"] = "text/css; charset=utf-8"
                     else:
                        headers["content-type"] = "text/html; charset=utf-8"
            
            content_bytes, headers = await process_content(resp.content, str(resp.url), headers)
            return Response(content=content_bytes, status_code=resp.status_code, headers=headers)
            
    except Exception as e:
        print(f"Proxy Error: {e}")
        # Return a user-friendly error message
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Proxy Error</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                    background: #1a1a1a;
                    color: #fff;
                }}
                .error-container {{
                    text-align: center;
                    padding: 2rem;
                }}
                h1 {{ color: #ef4444; margin-bottom: 1rem; }}
                p {{ color: #9ca3af; line-height: 1.6; }}
                code {{ background: #2a2a2a; padding: 0.2rem 0.5rem; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <div class="error-container">
                <h1>⚠️ Unable to Load Site</h1>
                <p>This website (<code>{url}</code>) cannot be loaded in the Device Lab.</p>
                <p>The site is using bot protection or blocking iframe embedding.</p>
                <p><strong>Suggestion:</strong> Try a different URL or open this site directly in your browser.</p>
            </div>
        </body>
        </html>
        """
        return Response(content=error_html, status_code=200, headers={"Content-Type": "text/html; charset=utf-8"})




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)


# ========== AUDIT MANAGEMENT ENDPOINTS ==========

@app.delete("/api/audit/{session_id}")
async def delete_audit_session(session_id: str, 
                             user: models.User = Depends(require_auth), 
                             db: Session = Depends(auth.get_db)):
    """Delete an audit session and all associated data"""
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Delete files
    try:
        # Static screenshots
        if os.path.exists(f"screenshots/{session_id}"):
            shutil.rmtree(f"screenshots/{session_id}")
            
        # Dynamic videos
        if os.path.exists(f"videos/{session_id}"):
            shutil.rmtree(f"videos/{session_id}")
            
    except Exception as e:
        print(f"Error deleting files for session {session_id}: {e}")
        # Continue deleting DB record even if file deletion fails
        
    # Delete DB record (Cascading delete should handle related results if configured, 
    # but let's manually delete if not sure about models configuration)
    
    # Manually delete related records just in case
    db.query(models.StaticAuditResult).filter(models.StaticAuditResult.session_id == session_id).delete()
    db.query(models.DynamicAuditResult).filter(models.DynamicAuditResult.session_id == session_id).delete()
    db.query(models.PerformanceAuditResult).filter(models.PerformanceAuditResult.session_id == session_id).delete()
    db.query(models.PhoneAuditResult).filter(models.PhoneAuditResult.session_id == session_id).delete()
    # Add other result types if any
    
    db.delete(session)
    db.commit()
    
    return {"message": "Session deleted successfully"}

@app.post("/api/audit/{session_id}/restart")
async def restart_audit_session(session_id: str, 
                              background_tasks: BackgroundTasks,
                              user: models.User = Depends(require_auth), 
                              db: Session = Depends(auth.get_db)):
    """Restart an existing audit session by creating a new one with same config"""
    old_session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id).first()
    if not old_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Create new session ID
    new_session_id = str(uuid.uuid4())
    
    # Create new session object copying config from old one
    new_session = models.AuditSession(
        session_id=new_session_id,
        user_id=user.id,
        name=f"{old_session.name} (Restart)",
        urls=old_session.urls,
        browsers=old_session.browsers,
        resolutions=old_session.resolutions,
        session_type=old_session.session_type,
        status="running",
        total_expected=old_session.total_expected, # Initial estimate, will be updated
        completed=0,
        created_at=datetime.utcnow()
    )
    
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    # Parse config
    urls = json.loads(new_session.urls) if new_session.urls else []
    
    # Re-trigger based on type using NEW session ID
    if new_session.session_type == "static":
        browsers = json.loads(new_session.browsers) if new_session.browsers else []
        resolutions = json.loads(new_session.resolutions) if new_session.resolutions else []
        background_tasks.add_task(static_audit_task, urls, browsers, resolutions, new_session_id, user.id, new_session.name)
        
    elif new_session.session_type == "dynamic":
        browsers = json.loads(new_session.browsers) if new_session.browsers else []
        resolutions = json.loads(new_session.resolutions) if new_session.resolutions else []
        background_tasks.add_task(dynamic_audit_task, urls, browsers, resolutions, new_session_id, user.id, new_session.name)
        
    elif new_session.session_type == "h1":
        background_tasks.add_task(h1_audit_task, urls, new_session_id, user.id, new_session.name)
        
    elif new_session.session_type == "performance":
         browsers = json.loads(new_session.browsers) if new_session.browsers else []
         strategy = browsers[0] if browsers else "desktop"
         background_tasks.add_task(audit_performance_task, urls, new_session_id, strategy)
         
    elif new_session.session_type == "meta-tags":
        background_tasks.add_task(audit_meta_tags_logic, urls, new_session_id)
         
    elif new_session.session_type == "phone":
        # Phone/CTA audit
        options = ["format", "links", "schema"] # Default options
        target_numbers = [] # Missing from session record currently
        background_tasks.add_task(phone_audit_task, urls, target_numbers, options, new_session_id, user.id, new_session.name)
         
    elif new_session.session_type == "sitemap":
         # Sitemap audit
         # Logic might expect a single URL
         target_url = urls[0] if urls else ""
         background_tasks.add_task(audit_sitemap_logic, target_url, new_session_id)

    return {"message": "Session restarted", "session_id": new_session_id, "old_session_id": session_id}

# ========== USER PROFILE ROUTE ==========
@app.get("/platform/settings", response_class=HTMLResponse)
async def user_profile(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(auth.get_db)):
    """Serve the user profile page with stats"""
    
    # Calculate stats - Show user-specific statistics
    total_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).count()
    completed_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id, models.AuditSession.status == "completed").count()
    
    # Total URLs Tested
    total_urls = 0
    sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).all()
    for s in sessions:
        if s.urls:
            try:
                url_list = json.loads(s.urls)
                total_urls += len(url_list)
            except:
                pass

    success_rate = 0
    if total_audits > 0:
        success_rate = int((completed_audits / total_audits) * 100)
        
    stats = {
        "total_sessions": total_audits,
        "completed_audits": completed_audits,
        "total_urls": total_urls,
        "success_rate": success_rate
    }
    
    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "stats": stats
    })

@app.get('/scan/keyword-rank', response_class=HTMLResponse)
async def keyword_rank_page(request: Request, user: models.User = Depends(get_current_user_from_cookie)):
    return templates.TemplateResponse('keyword_rank.html', {'request': request, 'user': user})