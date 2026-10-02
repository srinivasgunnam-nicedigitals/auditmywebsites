import os
import sys
import json
import asyncio
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from playwright.async_api import async_playwright
import uuid

import models
import auth
import database
from database import get_db, SessionLocal
from config import settings
from utils.ui import templates
from utils.tasks import running_tasks
from utils.security import is_safe_url
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits, check_user_credits
from utils.crawler import fetch_sitemap_urls

router = APIRouter()

BROWSER_ARGS = []
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
SKIP_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css', '.js',
             '.zip', '.xml', '.json', '.svg', '.ico', '.mp4', '.webp',
             '.woff', '.woff2', '.mp3', '.wav'}

# ========== AUDIT TASKS ==========

def h1_audit_task(urls: List[str], session_id: str, user_id: int, session_name: str, crawl_url: Optional[str] = None):
    """Sync wrapper — runs single-pass crawl+audit in a private thread."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_run_h1_audit(urls, session_id, user_id, crawl_url))


async def _navigate(page, url: str) -> bool:
    """Simple navigate mirroring ex.py success."""
    for attempt in range(3):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return True
        except Exception as e:
            err_str = str(e).lower()
            if ("err_" in err_str or "timeout" in err_str or "closed" in err_str) and attempt < 2:
                print(f"  [retry] {url}: {err_str[:50]}... ({attempt+1}/3)", flush=True)
                await asyncio.sleep(2)
                continue
            print(f"  [nav error] {url}: {e}", flush=True)
            return False


async def _run_h1_audit(urls: List[str], session_id: str, user_id: int, crawl_url: Optional[str]):
    """
    Single-pass crawl + H1 extraction.
    Each URL is visited ONCE: H1 tags are extracted AND new links are discovered
    in the same visit — no duplicate WAF challenge waits.
    """
    db = SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session:
            return

        is_crawl_mode = bool(crawl_url)
        start_url = crawl_url or (urls[0] if urls else None)
        extra_urls = urls if crawl_url else urls[1:]

        if start_url and not start_url.startswith(('http://', 'https://')):
            start_url = 'https://' + start_url
        start_url = start_url.rstrip('/')
            
        base_domain = urlparse(start_url).netloc.lower().replace("www.", "") if start_url else ""
        max_pages = 999999 if is_crawl_mode else len(urls)

        if not start_url:
            session.status = "error"
            await asyncio.to_thread(db.commit)
            return

        session.status = "crawling:Discovering & auditing pages..." if is_crawl_mode else "running"
        await asyncio.to_thread(db.commit)

        visited = set()
        completed_count = 0
        queue = asyncio.Queue()
        
        # Enqueue initial URLs
        await queue.put(start_url)
        for u in extra_urls:
            await queue.put(u)

        # Seed from sitemap if crawling
        if is_crawl_mode:
            print(f"DEBUG: Fetching sitemap for {start_url}...", flush=True)
            sitemap_urls = await fetch_sitemap_urls(start_url)
            print(f"DEBUG: Found {len(sitemap_urls)} URLs in sitemap", flush=True)
            for su in sitemap_urls:
                su = su.rstrip('/')
                if su != start_url and su not in extra_urls:
                    parsed = urlparse(su)
                    if base_domain in parsed.netloc and not any(su.lower().endswith(ext) for ext in SKIP_EXTS):
                        await queue.put(su)


        MAX_WORKERS = 10

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800}
            )

            async def worker():
                nonlocal completed_count
                page = await context.new_page()
                local_db = SessionLocal()
                try:
                    while True:
                        # Blocking wait — never exits early during WAF delays
                        url = await queue.get()

                        if url is None:          # sentinel → shutdown
                            queue.task_done()
                            break

                        # Normalize URL
                        norm_url = url.rstrip('/')
                        if norm_url in visited:
                            queue.task_done()
                            continue

                        if any(x in norm_url for x in ['get=sound', '.mp3', '.wav']):
                            queue.task_done()
                            continue

                        visited.add(norm_url)
                        print(f"  [h1] {url} (Total: {len(visited)})", flush=True)

                        local_session = local_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if not local_session or local_session.status == "stopped":
                            queue.task_done()
                            break

                        # Safety check
                        if not is_safe_url(url):
                            local_db.add(models.H1AuditResult(
                                session_id=session_id, url=url, h1_count=0,
                                h1_texts="[]", issues=json.dumps(["URL blocked (Private IP)"])
                            ))
                            # Atomic update
                            local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                                models.AuditSession.completed: models.AuditSession.completed + 1,
                                models.AuditSession.total_expected: max(local_session.total_expected, len(visited))
                            })
                            await asyncio.to_thread(local_db.commit)
                            queue.task_done()
                            continue

                        # Credit deduction
                        try:
                            deducted, _ = check_and_deduct_credits(local_session.user_id, 1, local_db)
                            local_session.credits_used = (local_session.credits_used or 0) + deducted
                        except HTTPException:
                            local_session.status = "error: credits exhausted"
                            await asyncio.to_thread(local_db.commit)
                            queue.task_done()
                            break

                        h1_texts = []
                        issues = []
                        try:
                            success = await _navigate(page, url)
                            if success:
                                # 404 check
                                is_404 = False
                                try:
                                    title = await page.title()
                                    if "404" in title or "not found" in title.lower():
                                        is_404 = True
                                    # Also check status code if possible (depends on response which is in _navigate)
                                except Exception:
                                    pass

                                if is_404:
                                    issues.append("Page returned 404 Not Found")
                                else:
                                    try:
                                        await page.wait_for_selector("h1", timeout=5000)
                                    except Exception:
                                        pass

                                    # Faster wait for H1
                                    try:
                                        await page.wait_for_function(
                                            "() => { const h1s = document.querySelectorAll('h1'); return h1s.length > 0 && Array.from(h1s).some(h => h.innerText.trim().length > 0); }",
                                            timeout=5000
                                        )
                                    except Exception:
                                        pass

                                    h1_data = []
                                    # Retry evaluation if context is destroyed
                                    for attempt in range(3):
                                        try:
                                            h1_data = await page.evaluate("""() => {
                                                return Array.from(document.querySelectorAll('h1')).map(el => ({
                                                    text: el.innerText.trim(),
                                                    length: el.innerText.trim().length
                                                }));
                                            }""")
                                            break
                                        except Exception as e:
                                            if "Execution context was destroyed" in str(e) and attempt < 2:
                                                print(f"  [retry] Context destroyed on {url}, retrying {attempt+1}/3...", flush=True)
                                                await page.wait_for_timeout(2000)
                                                continue
                                            raise e

                                    h1_texts = [h['text'] for h in h1_data if h['text']]
                                    cnt = len(h1_data)
                                    # Count of H1s that actually have text
                                    text_cnt = len(h1_texts)
                                    
                                    if cnt == 0:
                                        issues.append("No H1 tag found")
                                    elif text_cnt == 0 and cnt > 0:
                                        issues.append("H1 tag found but content is empty")
                                    elif text_cnt > 1:
                                        issues.append(f"Multiple H1 tags found ({text_cnt})")
                                    
                                    for h in h1_data:
                                        if not h['text']:
                                            # We already added "H1 tag found but content is empty"
                                            pass
                                        elif h['length'] > 70:
                                            issues.append(f"H1 too long ({h['length']} chars)")
                                        elif h['length'] < 10:
                                            issues.append(f"H1 too short ({h['length']} chars)")

                                    # Discover links (crawl mode only)
                                    if is_crawl_mode:
                                        try:
                                            links = await page.evaluate(
                                                "Array.from(document.querySelectorAll('a')).map(e => e.href)"
                                            )
                                            for link in links:
                                                if not link or not isinstance(link, str):
                                                    continue
                                                clean = link.split('#')[0].strip().rstrip('/')
                                                if not clean:
                                                    continue
                                                parsed = urlparse(clean)
                                                link_netloc = parsed.netloc.lower().replace("www.", "")
                                                if link_netloc == base_domain and clean not in visited:
                                                    ext = '.' + clean.rsplit('.', 1)[-1].lower() if '.' in clean.rsplit('/', 1)[-1] else ''
                                                    if ext not in SKIP_EXTS and len(visited) < max_pages:
                                                        await queue.put(clean)
                                        except Exception as e:
                                            print(f"  [link error] {url}: {e}", flush=True)
                            else:
                                issues.append("Navigation failed")

                        except Exception as e:
                            print(f"  [h1 error] {url}: {e}", flush=True)
                            issues.append(f"Error: {str(e)[:200]}")

                        local_db.add(models.H1AuditResult(
                            session_id=session_id, url=url,
                            h1_count=len(h1_texts),
                            h1_texts=json.dumps(h1_texts),
                            issues=json.dumps(issues)
                        ))
                        # Atomic increment
                        local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                            models.AuditSession.completed: models.AuditSession.completed + 1,
                            models.AuditSession.total_expected: max(local_session.total_expected, len(visited))
                        })
                        await asyncio.to_thread(local_db.commit)
                        queue.task_done()

                except Exception as e:
                    print(f"  [h1 worker fatal] {e}", flush=True)
                    try: queue.task_done()
                    except Exception: pass
                finally:
                    try: await page.close()
                    except Exception: pass
                    try: local_db.close()
                    except Exception: pass

            workers = []
            for _ in range(MAX_WORKERS):
                workers.append(asyncio.create_task(worker()))
                await asyncio.sleep(2)

            await queue.join()                          # wait for every URL (incl. WAF-delayed)
            for _ in range(MAX_WORKERS):
                await queue.put(None)                   # sentinel per worker
            await asyncio.gather(*workers, return_exceptions=True)
            await browser.close()

        db.expire_all()
        db.refresh(session)
        if session.status not in ("stopped", "error: credits exhausted"):
            # Atomic increments already updated session.completed
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            await asyncio.to_thread(db.commit)

    except Exception as e:
        print(f"H1 Audit Fatal: {e}", flush=True)
        try:
            db.refresh(session)
            session.status = "error"
            await asyncio.to_thread(db.commit)
        except Exception:
            pass
    finally:
        db.close()

# ========== ROUTES ==========

@router.get("/platform/h1", response_class=HTMLResponse)
async def h1_audit_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("h1_tags.html", {"request": request, "user": user})

@router.get("/h1-audit")
async def h1_audit_redirect(request: Request, user = Depends(require_auth)):
    """Redirect old URL pattern to new one"""
    return await h1_audit_page(request, user)

@router.post("/upload/h1")
async def upload_h1(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    crawl_url: Optional[str] = Form(None),
    session_name: str = Form("My H1 Audit"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401, detail="Not authenticated")

    urls = []
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        urls.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
    if manual_urls:
        urls.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])

    if not urls and not crawl_url:
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    total_credits = len(urls) if urls else 1
    try:
        low_credit_warning = check_user_credits(user.id, total_credits, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = total_credits

    urls = list(dict.fromkeys(urls))
    session_id = f"h1_{uuid.uuid4().hex[:8]}"

    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        name=session_name,
        session_type="h1",
        status="crawling:Initializing..." if crawl_url else "running",
        credits_used=total_credits,
        total_expected=len(urls) if urls else 1,
        completed=0,
        urls=json.dumps(urls),
        browsers=json.dumps(["Default"]),
        resolutions=json.dumps(["Default"]),
        credits_balance=user.credits
    )
    db.add(new_session)
    db.commit()

    background_tasks.add_task(h1_audit_task, urls, session_id, user.id, session_name, crawl_url)
    running_tasks[session_id] = "h1"

    return JSONResponse({"session": session_id, "total_expected": len(urls) if urls else 1, "type": "h1", "low_credits": low_credit_warning})

@router.get("/h1-results/{session_id}")
async def h1_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")

    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")

    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)

    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    results_data = [{
        "url": r.url,
        "h1_count": r.h1_count,
        "h1_texts": json.loads(r.h1_texts),
        "issues": json.loads(r.issues)
    } for r in results]

    return templates.TemplateResponse("h1_report.html", {
        "request": request, "user": user, "session": session,
        "session_id": session_id, "results": results_data
    })

@router.get("/api/results/h1/{session_id}")
async def get_h1_results(session_id: str, request: Request, db: Session = Depends(get_db)):
    """API endpoint to get H1 audit results as JSON"""
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)

    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    return [{
        "url": r.url,
        "h1_count": r.h1_count,
        "h1_texts": json.loads(r.h1_texts) if r.h1_texts else [],
        "issues": json.loads(r.issues) if r.issues else []
    } for r in results]

@router.get("/results/h1/{session_id}")
async def results_h1_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await h1_results_view(session_id, request, db)
