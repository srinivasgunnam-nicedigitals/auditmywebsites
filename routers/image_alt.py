import os
import sys
import json
import re
import asyncio
import time
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse, urljoin
from collections import Counter, deque

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
import httpx
from bs4 import BeautifulSoup
import uuid

import models
import auth
import database
from database import get_db, SessionLocal
from config import settings
from utils.ui import templates
from utils.tasks import running_tasks
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits, check_user_credits
from utils.crawler import fetch_sitemap_urls, discover_urls


router = APIRouter()

SKIP_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css', '.js',
             '.zip', '.xml', '.json', '.svg', '.ico', '.mp4', '.webp',
             '.woff', '.woff2', '.mp3', '.wav', '.avi'}

# ========== HELPERS ==========


def get_relative_path(url, base_url):
    """Calculates path relative to the base_url root"""
    base_path = urlparse(base_url).path.rstrip('/')
    url_path = urlparse(url).path
    if url_path.startswith(base_path):
        rel = url_path[len(base_path):]
        return rel if rel.startswith('/') else '/' + rel
    return url_path

# ========== AUDIT TASKS ==========

async def audit_image_alt_logic(urls: List[str], session_id: str):
    """Background task for Image Alt audit."""
    db = SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        sem = asyncio.Semaphore(15) # Balanced concurrency for faster but stable audits
        
        async with httpx.AsyncClient(
            follow_redirects=True, 
            verify=False, 
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=20)
        ) as client:
            # Get user_id from session for credit deduction
            user_id = session.user_id
            completed_count = 0
            
            async def process_url(url):
                nonlocal completed_count
                async with sem:
                    task_db = SessionLocal()
                    try:
                        # Check if session stopped or credits exhausted
                        task_session = task_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if not task_session or task_session.status == "stopped" or "error: credits exhausted" in task_session.status:
                            return

                        # Progressive Credit Deduction
                        try:
                            deducted, _ = check_and_deduct_credits(user_id, 1, task_db)
                            task_session.credits_used = (task_session.credits_used or 0) + deducted
                        except HTTPException as e:
                            if "credits" in str(e).lower():
                                task_session.status = "error: credits exhausted"
                                await asyncio.to_thread(task_db.commit)
                            return

                        max_retries = 3
                        retry_delay = 2 # seconds
                        last_error = "Unknown"

                        for attempt in range(max_retries):
                            try:
                                if attempt > 0:
                                    await asyncio.sleep(retry_delay * attempt)

                                resp = await client.get(url)
                                html = resp.text
                                soup = BeautifulSoup(html, "html.parser")
                                
                                images_alt = []
                                for img in soup.find_all('img'):
                                    src = img.get('src', '').strip()
                                    if src and not src.startswith('data:'):
                                        alt = img.get('alt', '').strip()
                                        images_alt.append({'src': src, 'alt': alt})
                                
                                score = 100
                                missing_alts = [img for img in images_alt if not img['alt']]
                                if images_alt:
                                    penalty = (len(missing_alts) / len(images_alt)) * 100
                                    score -= penalty
                                
                                score = max(0, int(score))
                                
                                result = models.ImageAltResult(
                                    session_id=session_id,
                                    url=url,
                                    images_alt=json.dumps(images_alt),
                                    score=score
                                )
                                task_db.add(result)
                                
                                # Atomic update
                                task_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                                    models.AuditSession.completed: models.AuditSession.completed + 1
                                })
                                # Use to_thread for blocking commit
                                await asyncio.to_thread(task_db.commit)
                                return 

                            except (httpx.RemoteProtocolError, httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
                                last_error = str(e)
                                if attempt == max_retries - 1: break
                            except Exception as e:
                                last_error = str(e)
                                break

                        # Fail result
                        try:
                            fail_result = models.ImageAltResult(
                                session_id=session_id,
                                url=url,
                                images_alt=json.dumps([]),
                                score=0
                            )
                            task_db.add(fail_result)
                            # Atomic update
                            task_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                                models.AuditSession.completed: models.AuditSession.completed + 1
                            })
                            await asyncio.to_thread(task_db.commit)
                        except: pass
                    finally:
                        task_db.close()

            await asyncio.gather(*[process_url(u) for u in urls])

            db.expire_all()
            if session:
                db.refresh(session)
                if session.status != "stopped":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                    await asyncio.to_thread(db.commit)
    except Exception as e:
        print(f"Image Alt audit failed: {e}")
        if session:
            db.refresh(session)
            session.status = "error"
            await asyncio.to_thread(db.commit)
    finally:
        db.close()

def run_image_alt_crawl_and_audit(urls: List[str], session_id: str, live_base: str, staging_base: str, crawl_site: bool):
    """Sync wrapper — runs async crawl+audit in a private thread with Proactor event loop."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_run_image_alt_crawl_and_audit(urls, session_id, live_base, staging_base, crawl_site))

async def _run_image_alt_crawl_and_audit(urls: List[str], session_id: str, live_base: str, staging_base: str, crawl_site: bool):
    """Background task to crawl and then audit"""
    final_urls = []
    if crawl_site and live_base and staging_base:
        found_count = 0
        lock = asyncio.Lock()
        
        async def on_progress(n):
            nonlocal found_count
            async with lock:
                found_count += n
                if found_count % 50 == 0 or (found_count < 100 and found_count % 10 == 0):
                    db_prog = SessionLocal()
                    try:
                        s = db_prog.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if s:
                            # Atomic increment
                            db_prog.query(models.AuditSession).filter_by(session_id=session_id).update({
                                models.AuditSession.completed: models.AuditSession.completed + n
                            })
                            await asyncio.to_thread(db_prog.commit)
                    finally:
                        db_prog.close()

        db = SessionLocal()
        try:
            s = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if s:
                s.status = "crawling:Discovering pages..."
                await asyncio.to_thread(db.commit)
            
            live_task = discover_urls(live_base, max_pages=2000, max_time=600, progress_callback=on_progress)
            staging_task = discover_urls(staging_base, max_pages=2000, max_time=600, progress_callback=on_progress)
            
            live_pages, staging_pages = await asyncio.gather(live_task, staging_task)
            
            paths = set()
            for p in live_pages: paths.add(get_relative_path(p, live_base))
            for p in staging_pages: paths.add(get_relative_path(p, staging_base))
            
            for rel_path in sorted(list(paths)):
                final_urls.append(urljoin(live_base, rel_path.lstrip('/')))
                final_urls.append(urljoin(staging_base, rel_path.lstrip('/')))
            
            if s:
                s.urls = json.dumps(final_urls)
                s.total_expected = len(final_urls)
                s.completed = 0  # Reset — crawl phase done, audit phase starting
                s.status = "running"
                await asyncio.to_thread(db.commit)

        finally:
            db.close()
    elif crawl_site and urls:
        found_count = 0
        lock = asyncio.Lock()
        
        async def on_progress(n):
            nonlocal found_count
            async with lock:
                found_count += n
                if found_count % 50 == 0 or (found_count < 100 and found_count % 10 == 0):
                    db_prog = SessionLocal()
                    try:
                        s = db_prog.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if s:
                            # Atomic increment
                            db_prog.query(models.AuditSession).filter_by(session_id=session_id).update({
                                models.AuditSession.completed: models.AuditSession.completed + n
                            })
                            await asyncio.to_thread(db_prog.commit)
                    finally:
                        db_prog.close()

        db = SessionLocal()
        try:
            s = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if s:
                s.status = "crawling:Discovering pages..."
                await asyncio.to_thread(db.commit)
            
            tasks = [discover_urls(u, max_pages=2000, max_time=600, progress_callback=on_progress) for u in urls]
            results = await asyncio.gather(*tasks)
            
            discovered_urls = set()
            for r in results:
                discovered_urls.update(r)
            
            if not discovered_urls:
                final_urls = urls
            else:
                final_urls = sorted(list(discovered_urls))

            if s:
                s.urls = json.dumps(final_urls)
                s.total_expected = len(final_urls)
                s.completed = 0  # Reset — crawl phase done, audit phase starting
                s.status = "running"
                await asyncio.to_thread(db.commit)
        finally:
            db.close()
    else:
        final_urls = urls

    await audit_image_alt_logic(final_urls, session_id)

# ========== ROUTES ==========

@router.get("/platform/image-alt", response_class=HTMLResponse)
async def image_alt_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("image_alt_audit.html", {"request": request, "user": user})

@router.post("/upload/image-alt")
async def upload_image_alt(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    live_url: Optional[str] = Form(None),
    staging_url: Optional[str] = Form(None),
    crawl_site: Optional[str] = Form(None),
    session_name: str = Form("My Image Alt Scan"),
    user: models.User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    urls = []
    is_crawling = crawl_site == "true"
    
    if live_url: urls.append(live_url)
    if staging_url: urls.append(staging_url)
    
    if manual_urls:
         urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    if not urls and not is_crawling: return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    # Credit deduction (1 per input URL)
    total_credits = len(urls)
    if total_credits == 0 and is_crawling: total_credits = 1

    try:
        low_credit_warning = check_user_credits(user.id, total_credits, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = total_credits

    urls = list(dict.fromkeys(urls))

    session_id = f"imalt_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="image-alt",
        name=session_name,
        urls=json.dumps(urls),
        browsers=json.dumps(["Internal"]),
        resolutions=json.dumps(["Default"]),
        total_expected=len(urls) if not is_crawling else 1,
        status="running" if not is_crawling else "crawling:Initializing...",
        completed=0,
        credits_balance=user.credits
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(run_image_alt_crawl_and_audit, urls, session_id, live_url, staging_url, is_crawling)
    running_tasks[session_id] = "image-alt"
    
    return JSONResponse({"session": session_id, "total_expected": len(urls) if not is_crawling else 1, "type": "image-alt", "low_credits": low_credit_warning})

@router.get("/results/image-alt/{session_id}")
async def image_alt_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    
    results = db.query(models.ImageAltResult).filter_by(session_id=session_id).all()
    
    urls = json.loads(session.urls)
    
    unique_domains = set()
    for u in urls:
        try:
            netloc = urlparse(u).netloc.replace("www.", "")
            unique_domains.add(netloc)
        except: pass
        
    is_comparison = len(unique_domains) == 2 or len(urls) == 2
    
    paired_results = []
    # Heuristic: Group by Netloc to find the two environments
    from collections import defaultdict
    grouped_urls = defaultdict(list)
    by_path = {}
    
    for r in results:
        parsed = urlparse(r.url)
        grouped_urls[parsed.netloc].append(r.url)
        
    if is_comparison:
        if len(grouped_urls) == 2:
            domains = list(grouped_urls.keys())
            
            def get_common_base(url_list):
                if not url_list: return ""
                s0 = url_list[0]
                parsed0 = urlparse(s0)
                base_host = f"{parsed0.scheme}://{parsed0.netloc}"
                paths = [urlparse(u).path for u in url_list]
                common = os.path.commonprefix(paths)
                if not common.endswith('/') and '/' in common:
                    common = common.rsplit('/', 1)[0] + '/'
                return base_host + common

            base1 = get_common_base(grouped_urls[domains[0]])
            base2 = get_common_base(grouped_urls[domains[1]])
            
            live_root = base1
            staging_root = base2
            
            input_urls = json.loads(session.urls) if session.urls else []
            if input_urls:
                first_input_netloc = urlparse(input_urls[0]).netloc
                if first_input_netloc == domains[1]:
                    live_root = base2
                    staging_root = base1
            
            for r in results:
                if r.url.startswith(live_root):
                    path = get_relative_path(r.url, live_root)
                    if path not in by_path: by_path[path] = {}
                    by_path[path]['live'] = r
                elif r.url.startswith(staging_root):
                    path = get_relative_path(r.url, staging_root)
                    if path not in by_path: by_path[path] = {}
                    by_path[path]['staging'] = r
        elif len(urls) == 2:
            live_url = urls[0]
            staging_url = urls[1]
            path = urlparse(live_url).path or "/"
            by_path[path] = {}
            live_res = next((r for r in results if r.url == live_url), None)
            staging_res = next((r for r in results if r.url == staging_url), None)
            if live_res: by_path[path]['live'] = live_res
            if staging_res: by_path[path]['staging'] = staging_res
        else:
            for r in results:
                path = urlparse(r.url).path or "/"
                if path not in by_path: by_path[path] = {}
                by_path[path]['live'] = r
    else:
        # Just a list of results, no comparison
        for r in results:
            # Use URL as key to be safe for multiple URLs
            by_path[r.url] = {'live': r}
    
    for key in sorted(by_path.keys()):
        val = by_path[key]
        live_res = val.get('live')
        staging_res = val.get('staging')
        
        def result_to_dict(obj):
            if not obj: return None
            d = {}
            for c in obj.__table__.columns:
                val = getattr(obj, c.name)
                if isinstance(val, datetime):
                    d[c.name] = val.isoformat()
                else:
                    d[c.name] = val
            return d

        path_val = key
        if not is_comparison and live_res:
            path_val = live_res.url
        elif not is_comparison and not live_res:
            # Should not happen with current logic, but for safety:
            path_val = key

        paired_results.append({
            'path': path_val,
            'live': result_to_dict(live_res),
            'staging': result_to_dict(staging_res)
        })

    return templates.TemplateResponse("image_alt_report.html", {
        "request": request, 
        "user": user, 
        "session": session, 
        "session_id": session_id, 
        "results": results,
        "is_site_comparison": is_comparison,
        "paired_results": paired_results,
        "live_url": urls[0] if len(urls) > 0 else "",
        "staging_url": urls[1] if len(urls) >= 2 else ""
    })

@router.get("/api/results/image-alt/{session_id}")
async def api_results_image_alt(session_id: str, request: Request, db: Session = Depends(get_db)):
    """JSON API — returns image-alt audit results for a session."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    results = db.query(models.ImageAltResult).filter_by(session_id=session_id).all()
    return JSONResponse({
        "session_id": session_id,
        "status": session.status,
        "results": [
            {
                "url": r.url,
                "score": r.score,
                "images": json.loads(r.images_alt) if r.images_alt else [],
                "image_count": len(json.loads(r.images_alt)) if r.images_alt else 0,
            }
            for r in results
        ]
    })
