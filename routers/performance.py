import os
import sys
import json
import asyncio
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from playwright.async_api import async_playwright

import models
import auth
import database
from database import get_db, SessionLocal
from config import settings
from utils.ui import templates
from utils.tasks import running_tasks
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits, check_user_credits
from utils.security import is_safe_url
from utils.crawler import fetch_sitemap_urls

router = APIRouter()

BROWSER_ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
USER_AGENT_DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
SKIP_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css', '.js',
             '.zip', '.xml', '.json', '.svg', '.ico', '.mp4', '.webp',
             '.woff', '.woff2', '.mp3', '.wav'}

# ========== AUDIT TASKS ==========

def audit_performance_task(urls: List[str], session_id: str, strategies: List[str] = ["desktop"], crawl_url: Optional[str] = None):
    """Sync wrapper to run performance audit in a private thread with Proactor loop."""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_run_performance_audit(urls, session_id, strategies, crawl_url))


async def _navigate(page, url: str) -> bool:
    """Navigate with WAF/challenge detection."""
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


async def _run_performance_audit(urls: List[str], session_id: str, strategies: List[str], crawl_url: Optional[str]):
    """Background task for Performance audit using a single-pass crawl+audit approach."""
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

        # Queue items are (url, strategy)
        queue = asyncio.Queue()
        visited_tasks = set() # tracks (url, strategy)
        discovered_urls = set() # tracks which URLs we've extracted links from

        # Initial seed
        for s in strategies:
            queue.put_nowait((start_url, s))
            visited_tasks.add((start_url, s))
            for u in extra_urls:
                if (u, s) not in visited_tasks:
                    queue.put_nowait((u, s))
                    visited_tasks.add((u, s))

        # Sitemap seed (only for crawl mode)
        if is_crawl_mode:
            print(f"DEBUG: Fetching sitemap for {start_url}...", flush=True)
            sitemap_urls = await fetch_sitemap_urls(start_url)
            print(f"DEBUG: Found {len(sitemap_urls)} URLs in sitemap", flush=True)
            for su in sitemap_urls:
                if su != start_url and su not in extra_urls:
                    parsed = urlparse(su)
                    if base_domain in parsed.netloc and not any(su.lower().endswith(ext) for ext in SKIP_EXTS):
                        # Enqueue for all strategies
                        for str_s in strategies:
                            if (su, str_s) not in visited_tasks:
                                queue.put_nowait((su, str_s))
                                visited_tasks.add((su, str_s))

        completed_count = 0
        MAX_WORKERS = 5

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)

            async def worker():
                nonlocal completed_count
                local_db = SessionLocal()
                # We'll create contexts as needed for mobile/desktop
                try:
                    while True:
                        item = await queue.get()
                        if item is None:
                            queue.task_done()
                            break
                        
                        url, strategy = item
                        
                        print(f"  [perf] {url} [{strategy}] (Done: {completed_count})", flush=True)

                        local_session = local_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if not local_session or local_session.status == "stopped":
                            queue.task_done()
                            break

                        if not is_safe_url(url):
                            local_db.add(models.PerformanceAuditResult(
                                session_id=session_id, url=url, device_preset=strategy.capitalize(), score=0
                            ))
                            # Atomic update
                            local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                                models.AuditSession.completed: models.AuditSession.completed + 1
                            })
                            await asyncio.to_thread(local_db.commit)
                            queue.task_done()
                            continue

                        try:
                            deducted, _ = check_and_deduct_credits(local_session.user_id, 1, local_db)
                            local_session.credits_used = (local_session.credits_used or 0) + deducted
                        except HTTPException:
                            local_session.status = "error: credits exhausted"
                            await asyncio.to_thread(local_db.commit)
                            queue.task_done()
                            break

                        # Setup context for specific strategy
                        context = None
                        if strategy == "mobile":
                            context = await browser.new_context(**p.devices['iPhone 12'])
                        else:
                            context = await browser.new_context(user_agent=USER_AGENT_DESKTOP, viewport={"width": 1920, "height": 1080})
                        
                        page = await context.new_page()
                        
                        try:
                            success = await _navigate(page, url)
                            if success:
                                # Extract metrics
                                metrics = await page.evaluate("""() => {
                                    const timing = performance.timing;
                                    const paint = performance.getEntriesByType('paint');
                                    const fcp = paint.find(p => p.name === 'first-contentful-paint');
                                    const now = Date.now();
                                    const navigationStart = timing.navigationStart || now;
                                    return {
                                        ttfb: Math.max(0, timing.responseStart - navigationStart),
                                        dom_load: Math.max(0, timing.domContentLoadedEventEnd - navigationStart),
                                        page_load: Math.max(0, timing.loadEventEnd - navigationStart),
                                        fcp: fcp ? Math.round(fcp.startTime) : 0,
                                        resources: performance.getEntriesByType('resource').length
                                    };
                                }""")
                                
                                score = 100
                                if metrics['page_load'] > 2500: score -= 20
                                if metrics['page_load'] > 5000: score -= 20
                                if metrics['ttfb'] > 600: score -= 15
                                if metrics['fcp'] > 2000: score -= 15
                                if metrics['resources'] > 100: score -= 10
                                score = max(0, score)

                                local_db.add(models.PerformanceAuditResult(
                                    session_id=session_id,
                                    url=url,
                                    device_preset=strategy.capitalize(),
                                    ttfb=int(metrics['ttfb']),
                                    fcp=int(metrics['fcp']),
                                    dom_load=int(metrics['dom_load']),
                                    page_load=int(metrics['page_load']),
                                    resource_count=metrics['resources'],
                                    score=score
                                ))

                                # Link discovery (only once per URL, and only in crawl mode)
                                if is_crawl_mode and url not in discovered_urls:
                                    discovered_urls.add(url)
                                    try:
                                        links = await page.evaluate("Array.from(document.querySelectorAll('a')).map(e => e.href)")
                                        cur_visited_domain_urls = len({u for (u, s) in visited_tasks})
                                        for link in links:
                                            if not link or not isinstance(link, str): continue
                                            clean = link.split('#')[0].strip()
                                            if not clean: continue
                                            parsed = urlparse(clean)
                                            if parsed.netloc == base_domain:
                                                ext = '.' + clean.rsplit('.', 1)[-1].lower() if '.' in clean.rsplit('/', 1)[-1] else ''
                                                if ext not in SKIP_EXTS and cur_visited_domain_urls < max_pages:
                                                    # Add for ALL strategies
                                                    added_any = False
                                                    for s_inner in strategies:
                                                        if (clean, s_inner) not in visited_tasks:
                                                            await queue.put((clean, s_inner))
                                                            visited_tasks.add((clean, s_inner))
                                                            added_any = True
                                                    if added_any:
                                                        cur_visited_domain_urls += 1
                                    except Exception as e:
                                        print(f"  [link error] {url}: {e}", flush=True)
                            else:
                                local_db.add(models.PerformanceAuditResult(
                                    session_id=session_id, url=url, device_preset=strategy.capitalize(), score=0
                                ))
                        except Exception as e:
                            print(f"  [perf error] {url} [{strategy}]: {e}", flush=True)
                            local_db.add(models.PerformanceAuditResult(
                                session_id=session_id, url=url, device_preset=strategy.capitalize(), score=0
                            ))
                        finally:
                            await page.close()
                            await context.close()

                        # Atomic update
                        local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                            models.AuditSession.completed: models.AuditSession.completed + 1,
                            models.AuditSession.total_expected: max(local_session.total_expected, len(visited_tasks))
                        })
                        await asyncio.to_thread(local_db.commit)
                        queue.task_done()

                except Exception as e:
                    print(f"  [perf worker fatal] {e}", flush=True)
                    try: queue.task_done()
                    except Exception: pass
                finally:
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
            # Atomic updates already updated session.completed
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            await asyncio.to_thread(db.commit)

    except Exception as e:
        print(f"Performance Audit Fatal: {e}", flush=True)
        try:
            db.refresh(session)
            session.status = "error"
            await asyncio.to_thread(db.commit)
        except Exception:
            pass
    finally:
        db.close()

# ========== ROUTES ==========

@router.get("/platform/performance", response_class=HTMLResponse)
async def performance_audit_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("performance_audit.html", {"request": request, "user": user})

@router.post("/upload/performance")
async def upload_performance(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    strategies: str = Form("[\"desktop\"]"),
    session_name: str = Form("My Performance Audit"),
    crawl_url: Optional[str] = Form(None),
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

    urls = list(dict.fromkeys(urls))

    try:
        strategy_list = json.loads(strategies)
        if not isinstance(strategy_list, list) or not strategy_list:
            strategy_list = ["desktop"]
    except:
        strategy_list = ["desktop"]

    try:
        low_credit_warning = check_user_credits(user.id, (len(urls) if urls else 1) * len(strategy_list), db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    charge_amount = (len(urls) if urls else 1) * len(strategy_list)
    request.state.credits_used = charge_amount
    total = charge_amount
    session_id = f"perf_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="performance",
        name=session_name,
        urls=json.dumps(urls),
        browsers=json.dumps(strategy_list),
        resolutions=json.dumps(["Default"]),
        total_expected=total,
        status="crawling:Initializing..." if crawl_url else "running",
        completed=0,
        credits_balance=user.credits
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(audit_performance_task, urls, session_id, strategy_list, crawl_url)
    running_tasks[session_id] = "performance"

    return JSONResponse({"session": session_id, "total_expected": total, "type": "performance", "low_credits": low_credit_warning})

@router.get("/performance-results/{session_id}")
async def performance_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    
    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)
    
    results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("performance_report.html", {
        "request": request, "user": user, "session": session, "session_id": session_id, "results": results
    })

@router.get("/results/performance/{session_id}")
async def results_performance_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await performance_results_view(session_id, request, db)

@router.get("/api/results/performance/{session_id}")
async def api_results_performance(session_id: str, request: Request, db: Session = Depends(get_db)):
    """JSON API — returns performance audit results for a session."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
    return JSONResponse({
        "session_id": session_id,
        "status": session.status,
        "results": [
            {
                "url": r.url,
                "device": r.device_preset,
                "score": r.score,
                "ttfb_ms": r.ttfb,
                "fcp_ms": r.fcp,
                "dom_load_ms": r.dom_load,
                "page_load_ms": r.page_load,
                "resource_count": r.resource_count,
            }
            for r in results
        ]
    })
