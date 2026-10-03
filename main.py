import os
import sys
import uvicorn
import asyncio
import datetime
from contextlib import asynccontextmanager

# Fix for Windows asyncio loop - Playwright requires ProactorEventLoop for subprocess support
if sys.platform.startswith("win"):
    print("[SYSTEM] Setting WindowsProactorEventLoopPolicy...", flush=True)
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

import database
import models
from config import settings
from database import get_db, SessionLocal
from utils.ui import templates
from routers.auth import get_current_user_from_cookie
from sqlalchemy.orm import Session
from fastapi import Depends

# ── Watchdog: auto-expire sessions stuck in running/crawling > 2 hours ──────

STUCK_SESSION_TIMEOUT_HOURS = 2
WATCHDOG_INTERVAL_SECONDS   = 15 * 60   # check every 15 minutes

async def _watchdog_loop():
    """Background task: marks sessions stuck for > STUCK_SESSION_TIMEOUT_HOURS as error."""
    await asyncio.sleep(60)  # brief startup delay so DB is fully ready
    while True:
        try:
            db = SessionLocal()
            try:
                cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=STUCK_SESSION_TIMEOUT_HOURS)
                stuck = (
                    db.query(models.AuditSession)
                    .filter(
                        models.AuditSession.created_at < cutoff,
                        models.AuditSession.completed_at.is_(None),
                        models.AuditSession.status.notin_(
                            ["completed", "stopped", "error",
                             "error: credits exhausted"]
                        ),
                    )
                    .all()
                )
                if stuck:
                    print(f"[Watchdog] Found {len(stuck)} stuck session(s) — marking as error.", flush=True)
                for session in stuck:
                    print(f"  [Watchdog] Expiring {session.session_id} "
                          f"(type={session.session_type}, status={session.status}, "
                          f"created={session.created_at})", flush=True)
                    session.status = "error"
                    session.completed_at = datetime.datetime.utcnow()
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[Watchdog] Error during check: {e}", flush=True)

        await asyncio.sleep(WATCHDOG_INTERVAL_SECONDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the session watchdog on app startup; cancel it on shutdown."""
    task = asyncio.create_task(_watchdog_loop())
    print("[Watchdog] Session watchdog started "
          f"(timeout={STUCK_SESSION_TIMEOUT_HOURS}h, interval={WATCHDOG_INTERVAL_SECONDS//60}m).", flush=True)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        print("[Watchdog] Session watchdog stopped.", flush=True)

# Import all routers
from routers import auth, responsive, performance, accessibility, h1, meta_tags, phone, sitemaps, platform, seo, image_alt, export, contact, admin, comparison

load_dotenv()

# Create necessary directories
os.makedirs("screenshots", exist_ok=True)
os.makedirs("videos", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("temp_frames", exist_ok=True)
os.makedirs("templates", exist_ok=True)
os.makedirs("diffs", exist_ok=True)
os.makedirs("reports", exist_ok=True)

# Initialize database
database.Base.metadata.create_all(bind=database.engine)

# Initialize FastAPI app
app = FastAPI(title="SiteTester Pro", version="2.0.0", lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware to handle .html redirects for legacy UI links
@app.middleware("http")
async def redirect_html_extension(request: Request, call_next):
    path = request.url.path
    if path.endswith(".html") and not path.startswith("/reports/"):
        new_path = path[:-5]
        # Special mappings
        if "device_lab" in new_path: new_path = "/platform/device-lab"
        if "audit_history" in new_path: new_path = "/platform/history"
        if "performance_audit" in new_path: new_path = "/platform/performance"
        if "accessibility_audit" in new_path: new_path = "/platform/accessibility"
        if "phone_validator" in new_path: new_path = "/phone-audit"
        if "h1_tags" in new_path: new_path = "/h1-audit"
        if "metatags" in new_path: new_path = "/scan/meta-tags"
        if "sitemaps" in new_path: new_path = "/scan/xml-sitemaps"
        
        return RedirectResponse(url=new_path, status_code=301)
    
    response = await call_next(request)
    return response

# Redis for active users tracking
try:
    import redis
    # Add timeouts to prevent hanging if Redis is not installed/running
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
    redis_client.ping() # Test connection immediately
    print("Successfully connected to Redis for active user tracking.")
except Exception as e:
    redis_client = None
    print(f"Warning: Redis not available (tracking disabled): {e}")

def _sync_track_user(user_id, path, method, ip_address, credits_used=0):
    """Runs in a background thread to avoid blocking the event loop"""
    if redis_client:
        try:
            redis_client.set(f"active_user:{user_id}", "1", ex=60)
        except:
            pass
            
    from database import SessionLocal
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        current_balance = user.credits if user else None
        
        log_entry = models.UserLog(
            user_id=user_id,
            endpoint=path,
            method=method,
            ip_address=ip_address,
            credits_used=credits_used,
            credits_balance=current_balance
        )
        db.add(log_entry)
        db.commit()
    except Exception as db_err:
        print(f"Failed to log user activity: {db_err}")
    finally:
        db.close()

@app.middleware("http")
async def admin_tracking_middleware(request: Request, call_next):
    # Continue if we are getting static files, otherwise we log everything
    path = request.url.path
    
    response = await call_next(request)
    
    # We shouldn't log static files or internal endpoints
    if any(path.startswith(prefix) for prefix in ["/static", "/screenshots", "/videos", "/temp_frames", "/diffs", "/.well-known"]):
        return response
        
    # Get user token
    token = request.cookies.get("access_token")
    if token:
        try:
            import auth
            user_id = auth.verify_token(token)
            if user_id:
                ip_address = request.client.host if request.client else None
                credits_used = getattr(request.state, "credits_used", 0)
                loop = asyncio.get_running_loop()
                # Run the blocking DB & Redis calls in a background thread 
                # so it doesn't delay the HTTP response
                loop.run_in_executor(None, _sync_track_user, user_id, path, request.method, ip_address, credits_used)
        except Exception as e:
            pass # Suppress tracking errors
            
    return response

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
app.mount("/videos", StaticFiles(directory="videos"), name="videos")
app.mount("/diffs", StaticFiles(directory="diffs"), name="diffs")
app.mount("/reports", StaticFiles(directory="reports"), name="reports")

# Landing page route
@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request, db: Session = Depends(get_db)):
    """Serve the public landing page, or redirect to dashboard if logged in"""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/platform/dashboard", status_code=302)
    return templates.TemplateResponse("landing.html", {
        "request": request,
        "google_client_id": settings.google_client_id,
        "user": user
    })

# Mount all routers
app.include_router(auth.router, tags=["Authentication"])
app.include_router(platform.router, tags=["Platform"])
app.include_router(responsive.router, tags=["Responsive Audits"])
app.include_router(performance.router, tags=["Performance Audits"])
app.include_router(accessibility.router, tags=["Accessibility Audits"])
app.include_router(h1.router, tags=["H1 Audits"])
app.include_router(meta_tags.router, tags=["Meta Tags Audits"])
app.include_router(phone.router, tags=["Phone Audits"])
app.include_router(sitemaps.router, tags=["Sitemap Audits"])
app.include_router(seo.router, tags=["SEO Tools"])
app.include_router(image_alt.router, tags=["Image Alt Audits"])
app.include_router(comparison.router, tags=["Content Comparison"])
app.include_router(export.router)
app.include_router(contact.router, tags=["Contact"])
app.include_router(admin.router, tags=["Admin"])

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "2.0.0"}

# Silence Chrome DevTools auto-request (avoids 404 log noise)
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_json():
    return {}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8090)
