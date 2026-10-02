import os
import json
import shutil
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
import re
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import uuid

import models
import auth
import database
from database import get_db, SessionLocal
from config import settings
from utils.ui import templates
from utils.tasks import running_tasks
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits

router = APIRouter()

# ========== HELPER FUNCTIONS ==========

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
        db.query(models.MetaTagsResult).filter_by(session_id=session_id).delete(synchronize_session=False)
        db.query(models.SitemapResult).filter_by(session_id=session_id).delete(synchronize_session=False)
    except Exception as e:
        print(f"Cleanup Error DB {session_id}: {e}")

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

# ========== ROUTES ==========

@router.get("/platform/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(get_db)):
    """Serve the dynamic dashboard page"""
    
    # 1. Stats
    running_audits = db.query(models.AuditSession).filter(models.AuditSession.status == "running", models.AuditSession.user_id == user.id).count()
    audits_completed = db.query(models.AuditSession).filter(models.AuditSession.status == "completed", models.AuditSession.user_id == user.id).count()
    
    urls_tested_result = db.query(func.sum(models.AuditSession.total_expected)).filter(models.AuditSession.status == "completed", models.AuditSession.user_id == user.id).scalar()
    urls_tested = int(urls_tested_result) if urls_tested_result else 0
    
    critical_findings_result = db.query(func.sum(models.AccessibilityAuditResult.critical_count))\
        .join(models.AuditSession, models.AuditSession.session_id == models.AccessibilityAuditResult.session_id)\
        .filter(models.AuditSession.user_id == user.id).scalar()
    critical_findings = int(critical_findings_result) if critical_findings_result else 0

    # 2. Recent Activity
    recent_audits = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).order_by(desc(models.AuditSession.created_at)).limit(10).all()
    
    activity_log = []
    for audit in recent_audits:
        # Use total_expected as the URL count for consistency with history page
        url_count = audit.total_expected or 0
        
        # Fallback to len(urls) if total_expected is 0 (though it should usually be set)
        if url_count == 0:
            try:
                urls_list = json.loads(audit.urls) if isinstance(audit.urls, str) else audit.urls
                if urls_list: url_count = len(urls_list)
            except: url_count = 0
            
        formatted_date = audit.created_at.strftime("%d-%m-%y, %I:%M %p").lower()

        type_map = {
            "static": "Responsive Audit",
            "performance": "Speed Test",
            "phone": "CTA Audit",
            "h1": "H1 Tags",
            "meta-tags": "Meta Tags",
            "sitemap": "XML Sitemaps",
            "accessibility": "Accessibility",
            "comparison": "Content Comparison"
        }
        display_type = type_map.get(audit.session_type, audit.session_type.replace("-", " ").title())

        activity_log.append({
            "session_id": audit.session_id,
            "name": audit.name or f"{display_type} Audit",
            "type": display_type,
            "status": audit.status.title(),
            "url_count": url_count,
            "date": formatted_date,
            "created_at_iso": f"{audit.created_at.isoformat()}Z",
            "completed": audit.completed,
            "total": audit.total_expected
        })

    # 3. Graph Data Placeholder (Can be expanded)
    graph_data = {
        "acc_total": 0, "perf_total": 0, "phone_total": 0, "h1_total": 0
    }

    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user": user,
        "running_audits": running_audits,
        "audits_completed": audits_completed,
        "urls_tested": urls_tested,
        "critical_findings": critical_findings,
        "recent_activity": activity_log
    })

@router.get("/platform/device-lab", response_class=HTMLResponse)
async def device_lab_view(request: Request, user: models.User = Depends(require_auth)):
    """Serve the device lab page"""
    return templates.TemplateResponse("device_lab.html", {"request": request, "user": user})

@router.get("/platform/history", response_class=HTMLResponse)
async def audit_history_page(request: Request, type: Optional[str] = None, page: int = 1, user: models.User = Depends(require_auth), db: Session = Depends(get_db)):
    """Unified Audit History page - requires authentication"""
    page_size = 10
    offset = (page - 1) * page_size
    
    query = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id)
    
    if type and type != 'all':
        query = query.filter(models.AuditSession.session_type == type)
        
    total_count = query.count()
    total_pages = (total_count + page_size - 1) // page_size
    
    sessions = query.order_by(desc(models.AuditSession.created_at)).offset(offset).limit(page_size).all()
    
    return templates.TemplateResponse("audit_history.html", {
        "request": request, 
        "user": user, 
        "sessions": sessions, 
        "active_type": type or 'all',
        "total_pages": total_pages,
        "current_page": page
    })

@router.get("/api/results/{session_id}")
async def get_any_results(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Generic results endpoint for all audit types"""
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
        
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session: raise HTTPException(status_code=404)
        
    if session.session_type == "static":
         results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
         return {"results": [{"url": r.url, "browser": r.browser, "resolution": r.resolution, "path": r.screenshot_path} for r in results]}
    elif session.session_type == "performance":
         results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
         return {"results": [{"url": r.url, "score": r.score, "strategy": r.device_preset} for r in results]}
    # Add other types as needed
    
    return {"results": [], "status": session.status}

@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
         
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404)
        
    try:
        perform_session_cleanup(session_id, db)
        db.delete(session)
        db.commit()
        return JSONResponse({"message": "Session deleted"})
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/api/sessions")
async def clear_all_sessions(request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id).all()
    deleted = 0
    for session in sessions:
        try:
            perform_session_cleanup(session.session_id, db)
            db.delete(session)
            db.commit()
            deleted += 1
        except:
            db.rollback()
            
    return JSONResponse({"message": f"History cleared. Deleted {deleted} sessions."})

@router.delete("/api/audit/{session_id}")
async def results_audit_delete(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Backward compatibility for audit deletion"""
    return await delete_session(session_id, request, db)

@router.post("/api/audit/{session_id}/restart")
async def restart_audit_session(session_id: str, 
                              background_tasks: BackgroundTasks,
                              request: Request,
                              db: Session = Depends(get_db)):
    """Restart an existing audit session by creating a new one with same config"""
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
        
    old_session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not old_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Credit deduction for restart
    try:
        urls_list = json.loads(old_session.urls) if old_session.urls else []
        charge_amount = len(urls_list)
        
        # New: Use multiplier for responsive audits
        if old_session.session_type in ["static", "dynamic"]:
            try:
                browsers_list = json.loads(old_session.browsers) if old_session.browsers else []
                res_list = json.loads(old_session.resolutions) if old_session.resolutions else []
                if browsers_list and res_list:
                    charge_amount = len(urls_list) * len(browsers_list) * len(res_list)
                elif charge_amount == 0:
                    charge_amount = 1
            except Exception as e:
                print(f"Error parsing session config for credit multiplier: {e}")
                if charge_amount == 0: charge_amount = 1
        # Heuristic for crawl-based sessions on restart
        elif old_session.session_type in ["meta-tags", "image-alt"] and len(urls_list) > 2:
             charge_amount = 1 # Treat as a new crawl initiation
        elif charge_amount == 0:
             charge_amount = 1 # Fallback
             
        # Only deduct upfront for non-progressive audits (static, dynamic, speed, etc.)
        # H1, Meta Tags, and Image Alt now use progressive deduction in their background tasks.
        if old_session.session_type in ["h1", "meta-tags", "image-alt"]:
            from utils.credits import check_user_credits
            low_credit_warning = check_user_credits(user.id, charge_amount, db)
        else:
            _, low_credit_warning = check_and_deduct_credits(user.id, charge_amount, db)
    except HTTPException as e:
        # For API endpoint, return JSON error
        return JSONResponse({"error": e.detail}, status_code=e.status_code)
    except Exception as e:
        print(f"Credit deduction error during restart: {e}")
        raise HTTPException(status_code=500, detail="Internal credit processing error")

    # Build a numbered restart name instead of appending "(Restart)"
    import re
    base_name = re.sub(r'\s*\((?:Restart|\d+)\)\s*$', '', old_session.name).strip()
    # Count existing sessions with the same base name to determine next number
    existing_count = db.query(models.AuditSession).filter(
        models.AuditSession.user_id == user.id,
        models.AuditSession.name.like(f"{base_name}%")
    ).count()
    restart_number = existing_count  # Original is 1, so restarts start from the count
    new_name = f"{base_name} ({restart_number})"

    new_session_id = str(uuid.uuid4())
    new_session = models.AuditSession(
        session_id=new_session_id,
        user_id=user.id,
        name=new_name,
        urls=old_session.urls,
        browsers=old_session.browsers,
        resolutions=old_session.resolutions,
        session_type=old_session.session_type,
        status="running",
        total_expected=old_session.total_expected,
        completed=0,
        created_at=datetime.utcnow()
    )
    
    db.add(new_session)
    db.commit()
    db.refresh(new_session)
    
    urls = json.loads(new_session.urls) if new_session.urls else []
    
    # Late imports to avoid circular dependencies
    if new_session.session_type == "static":
        from routers.responsive import static_audit_task
        browsers = json.loads(new_session.browsers) if new_session.browsers else []
        resolutions = json.loads(new_session.resolutions) if new_session.resolutions else []
        background_tasks.add_task(static_audit_task, urls, browsers, resolutions, new_session_id, user.id, new_session.name)
    elif new_session.session_type == "dynamic":
        from routers.responsive import dynamic_audit_task
        browsers = json.loads(new_session.browsers) if new_session.browsers else []
        resolutions = json.loads(new_session.resolutions) if new_session.resolutions else []
        background_tasks.add_task(dynamic_audit_task, urls, browsers, resolutions, new_session_id, user.id, new_session.name)
    elif new_session.session_type == "h1":
        from routers.h1 import h1_audit_task
        background_tasks.add_task(h1_audit_task, urls, new_session_id, user.id, new_session.name)
    elif new_session.session_type == "performance":
        from routers.performance import audit_performance_task
        strategies = json.loads(new_session.browsers) if new_session.browsers else ["desktop"]
        background_tasks.add_task(audit_performance_task, urls, new_session_id, strategies)
    elif new_session.session_type == "accessibility":
        from routers.accessibility import audit_accessibility_task
        background_tasks.add_task(audit_accessibility_task, urls, new_session_id)
    elif new_session.session_type == "meta-tags":
        from urllib.parse import urlparse as _urlparse
        # Detect if original was a crawl session: crawled sessions have many expanded URLs stored,
        # while direct sessions have only the originally provided URLs (typically 1-2).
        was_crawl = len(urls) > 2
        if was_crawl:
            from routers.meta_tags import run_meta_crawl_and_audit
            live_base = ""
            staging_base = ""
            if urls:
                p0 = _urlparse(urls[0])
                live_base = f"{p0.scheme}://{p0.netloc}"
            if len(urls) >= 2:
                p1 = _urlparse(urls[1])
                candidate = f"{p1.scheme}://{p1.netloc}"
                if candidate != live_base:
                    staging_base = candidate
            new_session.status = "crawling:Initializing..."
            new_session.completed = 0
            db.commit()
            root_urls = [live_base] if not staging_base else []
            background_tasks.add_task(run_meta_crawl_and_audit, root_urls, new_session_id, live_base, staging_base, True)
        else:
            # Direct URLs (no crawl) — just re-audit the same URLs
            from routers.meta_tags import audit_meta_tags_logic
            new_session.status = "running"
            new_session.completed = 0
            db.commit()
            background_tasks.add_task(audit_meta_tags_logic, urls, new_session_id)
    elif new_session.session_type == "image-alt":
        from routers.image_alt import audit_image_alt_logic
        new_session.status = "running"
        new_session.completed = 0
        db.commit()
        background_tasks.add_task(audit_image_alt_logic, urls, new_session_id)
    elif new_session.session_type == "phone":
        from routers.phone import phone_audit_task
        options = ["format", "links", "schema"] 
        target_numbers = [] 
        background_tasks.add_task(phone_audit_task, urls, target_numbers, options, new_session_id, user.id, new_session.name)
    elif new_session.session_type == "sitemap":
        from routers.sitemaps import audit_sitemap_logic
        target_url = urls[0] if urls else ""
        background_tasks.add_task(audit_sitemap_logic, target_url, new_session_id)

    return {"message": "Session restarted", "session_id": new_session_id, "old_session_id": session_id, "low_credits": low_credit_warning}

@router.get("/progress/{session_type}/{session_id}")
async def get_progress_typed(session_type: str, session_id: str, db: Session = Depends(get_db)):
    """Progress endpoint with session type prefix for backward compatibility"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session: return {"completed": 0, "total": 0, "status": "not_found"}
    
    # DEBUG: Print status to console to verify if crawling status is being saved
    if session.session_type == 'h1':
        print(f"DEBUG PROGRESS: ID={session_id} Status={session.status} Completed={session.completed}", flush=True)

    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@router.get("/progress/{session_id}")
async def get_progress(session_id: str, db: Session = Depends(get_db)):
    """Generic progress endpoint"""
    session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
    if not session: return {"completed": 0, "total": 0, "status": "not_found"}
    return {
        "completed": session.completed,
        "total": session.total_expected,
        "status": session.status
    }

@router.get("/platform/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: models.User = Depends(require_auth), db: Session = Depends(get_db)):
    """Serve the user profile page with user-specific stats"""
    
    # Calculate stats for the current user
    user_sessions = db.query(models.AuditSession).filter(models.AuditSession.user_id == user.id)
    total_audits = user_sessions.count()
    completed_audits = user_sessions.filter(models.AuditSession.status == "completed").count()
    
    success_rate = 0
    if total_audits > 0:
        success_rate = int((completed_audits / total_audits) * 100)
        
    stats = {
        "total_sessions": total_audits,
        "completed_audits": completed_audits,
        "success_rate": success_rate
    }
    
    # Detect if user signed in with Google
    is_google_user = False
    token = request.cookies.get("access_token")
    if token:
        try:
            import jwt as pyjwt
            payload = pyjwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
            if payload.get("auth_provider") == "google":
                is_google_user = True
        except Exception:
            pass

    return templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "stats": stats,
        "is_google_user": is_google_user
    })

@router.post("/api/live/search")
async def live_search(request: Request, url_data: dict, db: Session = Depends(get_db), current_user = Depends(get_current_user_from_cookie)):
    """Small endpoint to deduct credit when a user searches in Live Responsive"""
    from utils.credits import check_and_deduct_credits
    url = url_data.get("url")
    if not url:
        return JSONResponse(status_code=400, content={"error": "URL is required"})

    if not current_user:
        return JSONResponse(status_code=401, content={"error": "Authentication required"})

    try:
        # Deduct 1 credit for the search
        _, low_credit_warning = check_and_deduct_credits(current_user.id, 1, db)
        request.state.credits_used = 1
        return {"success": True, "low_credits": low_credit_warning}
    except ValueError as e:
        return JSONResponse(status_code=403, content={"error": str(e)})

@router.get("/api/proxy")
async def proxy_url(url: str):
    """Proxy endpoint to bypass X-Frame-Options with enhanced compatibility and SSRF protection"""
    from utils.security import is_safe_url
    import httpx
    import re
    import asyncio
    
    if not url.startswith("http"):
        url = "https://" + url

    # SSRF Protection
    if not is_safe_url(url):
        return HTMLResponse(
            content="<div style='color: white; background: #1a1a1a; padding: 20px; font-family: sans-serif;'>"
                    "<h3>Security Block</h3><p>The requested URL is blocked for security reasons (Private/Internal IP).</p></div>",
            status_code=403
        )

    async def process_content(content_bytes, final_url, headers):
        """Helper to inject base tag and clean HTML for proxying"""
        content_type = headers.get("content-type", "").lower()
        
        try:
            if "text/html" in content_type:
                html = content_bytes.decode("utf-8", errors="replace")
                flags = re.IGNORECASE | re.DOTALL

                # Cleanup Security Headers within HTML
                html = re.sub(r'<meta[^>]*http-equiv=["\']?(Content-Security-Policy|X-Frame-Options)["\']?[^>]*>', '', html, flags=flags)
                html = re.sub(r'\s+CSP=["\'][^"\']*["\']', '', html, flags=flags)
                html = re.sub(r'\s+(integrity|crossorigin)=["\'][^"\']*["\']', '', html, flags=flags)
                
                # Inject Base Tag & Referrer Policy
                base_tag = f'<base href="{final_url}">'
                referrer_tag = '<meta name="referrer" content="no-referrer">'
                injection = f"{base_tag}\n{referrer_tag}"
                
                if "<head" in html.lower():
                    html = re.sub(r'(<head[^>]*>)', f'\\1{injection}', html, count=1, flags=flags)
                elif "<html" in html.lower():
                    html = re.sub(r'(<html[^>]*>)', f'\\1<head>{injection}</head>', html, count=1, flags=flags)
                else:
                    html = f"<head>{injection}</head>" + html

                # Aggressive Script Sanitization
                bad_patterns = ['rocket-loader', 'data-cfasync', 'litespeed', 'autoptimize', 'wp-emoji']
                for pat in bad_patterns:
                    html = re.sub(fr'<script[^>]*{pat}[^>]*>.*?</script>', '<!-- Stripped Optimization Script -->', html, flags=flags)

                content_bytes = html.encode("utf-8")
                if "charset" not in content_type:
                    headers["content-type"] = "text/html; charset=utf-8"

            elif "text/css" in content_type:
                if "charset" not in content_type:
                    headers["content-type"] = "text/css; charset=utf-8"

        except Exception as e:
            print(f"Proxy clean error: {e}")
            
        return content_bytes, headers

    req_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, verify=False) as client:
            resp = await client.get(url, timeout=20.0, headers=req_headers)

            # Challenge detection (Cloudflare, etc.)
            is_challenge = resp.status_code in (202, 403, 429) or "sg-captcha" in resp.headers or "cf-mitigated" in resp.headers
            if is_challenge:
                print(f"  [proxy-challenge] Challenge detected on {url} (status {resp.status_code}), solving with Playwright...", flush=True)
                
                def solve_captcha_sync(t_url):
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
                        page.goto(t_url, wait_until="load", timeout=60000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=10000)
                        except:
                            pass
                        page.wait_for_timeout(15000)
                        content = page.content()
                        browser.close()
                        return content
                
                try:
                    pw_content = await asyncio.to_thread(solve_captcha_sync, url)
                    
                    excluded_headers = [
                        'x-frame-options', 'content-security-policy', 'frame-options',
                        'x-xss-protection', 'x-content-type-options', 'content-security-policy-report-only',
                        'content-encoding', 'transfer-encoding', 'content-length',
                        'connection', 'strict-transport-security'
                    ]
                    headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
                    content_bytes, headers = await process_content(pw_content.encode('utf-8', errors='replace'), str(resp.url), headers)
                    return Response(content=content_bytes, status_code=200, headers=headers)
                except Exception as pw_err:
                    import traceback
                    print(f"Playwright proxy error: {pw_err}")
                    traceback.print_exc()
                    await asyncio.sleep(15)
                    resp = await client.get(url, timeout=20.0, headers=req_headers)

            excluded_headers = [
                'x-frame-options', 'content-security-policy', 'frame-options',
                'x-xss-protection', 'x-content-type-options', 'content-security-policy-report-only',
                'content-encoding', 'transfer-encoding', 'content-length',
                'connection', 'strict-transport-security'
            ]
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded_headers}
            
            content_bytes, headers = await process_content(resp.content, str(resp.url), headers)
            return Response(content=content_bytes, status_code=resp.status_code, headers=headers)
            
    except Exception as e:
        print(f"Proxy Error: {e}")
        error_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Proxy Error</title>
            <style>
                body {{
                    font-family: sans-serif;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                    background: #1a1a1a;
                    color: #fff;
                }}
                .error-container {{ text-align: center; padding: 2rem; }}
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
            </div>
        </body>
        </html>
        """
        return Response(content=error_html, status_code=200, headers={"Content-Type": "text/html; charset=utf-8"})
