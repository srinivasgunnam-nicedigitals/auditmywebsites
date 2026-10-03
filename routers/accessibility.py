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
import httpx
import uuid

import models
import auth
import database
from database import get_db, SessionLocal
from config import settings
from utils.ui import templates
from utils.tasks import running_tasks
from utils.security import is_safe_url
from utils.security import is_safe_url
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits, check_user_credits
from utils.crawler import fetch_sitemap_urls

router = APIRouter()

BROWSER_ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
SKIP_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css', '.js',
             '.zip', '.xml', '.json', '.svg', '.ico', '.mp4', '.webp',
             '.woff', '.woff2', '.mp3', '.wav'}

# ========== AUDIT TASKS ==========

def audit_accessibility_task(urls: List[str], session_id: str, user_id: int, crawl_url: Optional[str] = None):
    """Sync wrapper - runs single-pass crawl+audit in a private thread with Proactor loop."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_run_accessibility_audit(urls, session_id, user_id, crawl_url))


async def _navigate(page, url: str) -> bool:
    """Navigate with WAF/challenge detection and waiting."""
    try:
        response = await page.goto(url, wait_until="load", timeout=90000)
        if response and (response.status == 202 or "sg-captcha" in response.headers):
            print(f"  [challenge] WAF on {url}, waiting 15s...", flush=True)
            await page.wait_for_timeout(15000)
            content = await page.content()
            if 'http-equiv="refresh"' in content:
                await page.wait_for_timeout(10000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        print(f"  [nav error] {url}: {e}", flush=True)
        return False


async def _run_accessibility_audit(urls: List[str], session_id: str, user_id: int, crawl_url: Optional[str]):
    """Background task for Accessibility audit using a single-pass crawl+audit approach."""
    db = SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session:
            return

        is_crawl_mode = bool(crawl_url)
        start_url = crawl_url or (urls[0] if urls else None)
        extra_urls = urls if crawl_url else urls[1:]
        base_domain = urlparse(start_url).netloc if start_url else ""
        max_pages = 999999 if is_crawl_mode else len(urls)

        if not start_url:
            session.status = "error"
            await asyncio.to_thread(db.commit)
            return

        session.status = "crawling:Discovering & auditing pages..." if is_crawl_mode else "running"
        await asyncio.to_thread(db.commit)

        # Fetch axe-core once
        axe_source = ""
        try:
            async with httpx.AsyncClient(verify=False) as client:
                for retry in range(3):
                    try:
                        resp = await client.get("https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.0/axe.min.js", timeout=15)
                        if resp.status_code == 200:
                            axe_source = resp.text
                            break
                    except Exception:
                        if retry == 2: raise
                        await asyncio.sleep(2 * (retry + 1))
        except Exception as e:
            print(f"Failed to fetch axe-core: {e}")
            session.status = "error: axe-core fetch failed"
            await asyncio.to_thread(db.commit)
            return

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
                if su != start_url and su not in extra_urls:
                    parsed = urlparse(su)
                    if base_domain in parsed.netloc and not any(su.lower().endswith(ext) for ext in SKIP_EXTS):
                        await queue.put(su)

        MAX_WORKERS = 3 # Axe is heavy, keep concurrency low

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 800}
            )

            async def worker():
                nonlocal completed_count
                page = await context.new_page()
                local_db = SessionLocal()
                try:
                    while True:
                        url = await queue.get()

                        if url is None:
                            queue.task_done()
                            break

                        if url in visited:
                            queue.task_done()
                            continue

                        if any(x in url for x in ['get=sound', '.mp3', '.wav']):
                            queue.task_done()
                            continue

                        visited.add(url)
                        print(f"  [a11y] {url} (Total: {len(visited)})", flush=True)

                        local_session = local_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if not local_session or local_session.status == "stopped":
                            queue.task_done()
                            break

                        if not is_safe_url(url):
                            local_db.add(models.AccessibilityAuditResult(
                                session_id=session_id, url=url, score=0,
                                violations_count=0, report_json="[]"
                            ))
                            # Atomic update
                            local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                                models.AuditSession.completed: models.AuditSession.completed + 1
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

                        violations = []
                        score = 0
                        try:
                            success = await _navigate(page, url)
                            if success:
                                # Run axe engine
                                await page.evaluate(axe_source)
                                results = await page.evaluate("axe.run()")
                                
                                violations = results.get('violations', [])
                                critical = sum(1 for v in violations if v.get('impact') == 'critical')
                                serious = sum(1 for v in violations if v.get('impact') == 'serious')
                                moderate = sum(1 for v in violations if v.get('impact') == 'moderate')
                                minor = sum(1 for v in violations if v.get('impact') == 'minor')
                                score = max(0, 100 - (critical * 10 + serious * 5 + moderate * 2))

                                if is_crawl_mode:
                                    try:
                                        links = await page.evaluate(
                                            "Array.from(document.querySelectorAll('a')).map(e => e.href)"
                                        )
                                        for link in links:
                                            if not link or not isinstance(link, str): continue
                                            clean = link.split('#')[0].strip()
                                            if not clean: continue
                                            parsed = urlparse(clean)
                                            if parsed.netloc == base_domain and clean not in visited:
                                                ext = '.' + clean.rsplit('.', 1)[-1].lower() if '.' in clean.rsplit('/', 1)[-1] else ''
                                                if ext not in SKIP_EXTS and len(visited) < max_pages:
                                                    await queue.put(clean)
                                    except Exception as e:
                                        print(f"  [link error] {url}: {e}", flush=True)

                            local_db.add(models.AccessibilityAuditResult(
                                session_id=session_id,
                                url=url,
                                score=score,
                                violations_count=len(violations),
                                critical_count=sum(1 for v in violations if v.get('impact') == 'critical'),
                                serious_count=sum(1 for v in violations if v.get('impact') == 'serious'),
                                moderate_count=sum(1 for v in violations if v.get('impact') == 'moderate'),
                                minor_count=sum(1 for v in violations if v.get('impact') == 'minor'),
                                report_json=json.dumps(violations)
                            ))
                        except Exception as e:
                            print(f"  [a11y error] {url}: {e}", flush=True)
                            local_db.add(models.AccessibilityAuditResult(
                                session_id=session_id, url=url, score=0, violations_count=0, report_json="[]"
                            ))

                        # Atomic update
                        local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                            models.AuditSession.completed: models.AuditSession.completed + 1,
                            models.AuditSession.total_expected: max(local_session.total_expected, len(visited))
                        })
                        await asyncio.to_thread(local_db.commit)
                        queue.task_done()

                except Exception as e:
                    print(f"  [a11y worker fatal] {e}", flush=True)
                    try: queue.task_done()
                    except Exception: pass
                finally:
                    try: await page.close()
                    except Exception: pass
                    try: local_db.close()
                    except Exception: pass

            workers = [asyncio.create_task(worker()) for _ in range(MAX_WORKERS)]
            await queue.join()
            for _ in range(MAX_WORKERS):
                await queue.put(None)
            await asyncio.gather(*workers, return_exceptions=True)
            await browser.close()

        db.expire_all()
        db.refresh(session)
        if session.status not in ("stopped", "error: credits exhausted"):
            # Atomic increments handled completion
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            await asyncio.to_thread(db.commit)

    except Exception as e:
        print(f"Accessibility Audit Fatal: {e}", flush=True)
        try:
            db.refresh(session)
            session.status = "error"
            await asyncio.to_thread(db.commit)
        except Exception:
            pass
    finally:
        db.close()

# ========== ROUTES ==========

@router.get("/platform/accessibility", response_class=HTMLResponse)
async def accessibility_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("accessibility_audit.html", {"request": request, "user": user})

@router.post("/upload/accessibility")
async def upload_accessibility(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    session_name: str = Form("My Accessibility Audit"),
    crawl_url: Optional[str] = Form(None),
    user: models.User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    url_list = []
    if manual_urls:
         url_list.extend([line.strip() for line in manual_urls.splitlines() if line.strip().startswith(("http://", "https://"))])
    if file:
        content = await file.read()
        text_content = content.decode("utf-8", errors="ignore")
        url_list.extend([line.strip() for line in text_content.splitlines() if line.strip().startswith(("http://", "https://"))])
    
    if not url_list and not crawl_url: 
        return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    url_list = list(dict.fromkeys(url_list))

    try:
        low_credit_warning = check_user_credits(user.id, len(url_list) if url_list else 1, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = len(url_list) if url_list else 1

    total = len(url_list) if not crawl_url else 1
    session_id = f"a11y_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="accessibility",
        name=session_name,
        urls=json.dumps(url_list),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["Default"]),
        total_expected=total,
        status="crawling:Initializing..." if crawl_url else "running",
        completed=0,
        credits_balance=user.credits
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_accessibility_task, url_list, session_id, user.id, crawl_url)
    running_tasks[session_id] = "accessibility"
    
    return JSONResponse({"session": session_id, "total_expected": total, "type": "accessibility", "low_credits": low_credit_warning})

@router.get("/accessibility-results/{session_id}")
async def accessibility_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    
    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)
    
    results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("accessibility_report.html", {
        "request": request, "user": user, "session": session, "session_id": session_id, "results": results
    })

@router.get("/results/accessibility/detail/{result_id}")
async def view_accessibility_detail(result_id: int, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
    
    result = db.query(models.AccessibilityAuditResult).filter_by(id=result_id).first()
    if not result: raise HTTPException(status_code=404, detail="Result not found")
        
    session = db.query(models.AuditSession).filter_by(session_id=result.session_id, user_id=user.id).first()
    if not session: raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        report_data = json.loads(result.report_json)
    except:
        report_data = []
        
    return templates.TemplateResponse("accessibility_detail.html", {
        "request": request, "user": user, "session": session, "result": result, "violations": report_data
    })

@router.get("/results/accessibility/{session_id}")
async def results_accessibility_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await accessibility_results_view(session_id, request, db)

@router.get("/api/results/accessibility/{session_id}")
async def api_results_accessibility(session_id: str, request: Request, db: Session = Depends(get_db)):
    """JSON API — returns accessibility audit results for a session."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
    return JSONResponse({
        "session_id": session_id,
        "status": session.status,
        "results": [
            {
                "url": r.url,
                "score": r.score,
                "violations_count": r.violations_count,
                "critical": r.critical_count,
                "serious": r.serious_count,
                "moderate": r.moderate_count,
                "minor": r.minor_count,
                "violations": json.loads(r.report_json) if r.report_json else [],
            }
            for r in results
        ]
    })
