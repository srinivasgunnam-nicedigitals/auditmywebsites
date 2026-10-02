import os
import re
import sys
import json
import asyncio
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from playwright.async_api import async_playwright
import uuid
import phonenumbers

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

# ========== BROWSER SETTINGS ==========
BROWSER_ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

SKIP_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css', '.js',
             '.zip', '.xml', '.json', '.svg', '.ico', '.mp4', '.webp',
             '.woff', '.woff2', '.mp3', '.wav'}

# ========== HELPER FUNCTIONS ==========

def normalize_phone(num: str) -> str:
    """Normalize phone number by extracting only digits for comparison"""
    return "".join(c for c in num if c.isdigit())

def find_phones_in_text(text: str, region: str = "US") -> set:
    """Use phonenumbers library + regex to extract phone numbers from text."""
    phones = set()
    if not text:
        return phones
    # 1. Industry-standard library
    try:
        for match in phonenumbers.PhoneNumberMatcher(text, region):
            formatted = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.NATIONAL)
            phones.add(formatted)
    except Exception:
        pass
    # 2. Broad regex fallback for partial/formatted numbers the library might miss
    pattern = r'(?:\+?\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}'
    for m in re.findall(pattern, text):
        m = m.strip()
        if m and len(normalize_phone(m)) >= 7:
            phones.add(m)
    return phones

# ========== PAGE NAVIGATION (SHARED) ==========

async def navigate_page(page, url: str) -> bool:
    """
    Navigate a page to a URL with full challenge/WAF handling.
    Returns True if successful, False if it should be skipped.
    """
    try:
        response = await page.goto(url, wait_until="load", timeout=90000)
        
        # Detect WAF / CAPTCHA challenge (e.g. Status 202, sg-captcha header, or meta-refresh)
        if response and (response.status == 202 or "sg-captcha" in response.headers):
            print(f"  [challenge] WAF on {url}, waiting 15s...", flush=True)
            await page.wait_for_timeout(15000)
            # Check if we're STILL on a refresh loop
            content = await page.content()
            if 'http-equiv="refresh"' in content:
                print(f"  [challenge] Still refreshing, waiting 10s more...", flush=True)
                await page.wait_for_timeout(10000)

        # Wait for network to calm down after challenge resolution
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        await page.wait_for_timeout(2000)  # Final stabilization
        return True

    except Exception as e:
        print(f"  [nav error] {url}: {e}", flush=True)
        return False

# ========== PHONE EXTRACTION FROM PAGE ==========

async def extract_phones_from_page(page) -> set:
    """
    Extract all phone numbers from a fully-loaded page using multiple strategies.
    """
    phones = set()

    async def safe_eval(expr):
        """Evaluate JS with retries for context-destroyed errors."""
        for attempt in range(3):
            try:
                return await page.evaluate(expr)
            except Exception as e:
                if "context was destroyed" in str(e) and attempt < 2:
                    await asyncio.sleep(1.5)
                    continue
                raise

    try:
        data = await safe_eval('''() => {
            return {
                text: document.body ? document.body.innerText : '',
                links: Array.from(document.querySelectorAll('a')).map(a => ({
                    href: a.getAttribute('href') || '',
                    text: a.innerText || ''
                })),
                metas: Array.from(document.querySelectorAll('meta')).map(m => ({
                    name: (m.getAttribute('name') || m.getAttribute('property') || '').toLowerCase(),
                    content: m.getAttribute('content') || ''
                })),
                jsonld: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.innerText)
            };
        }''')
    except Exception as e:
        print(f"  [extract error] Could not evaluate page: {e}", flush=True)
        return phones

    # 1. Body text (most reliable - catches "CALL: (717) 432-8184" style content)
    for p in find_phones_in_text(data.get('text', '')):
        phones.add(p)

    # 2. tel: links
    for link in data.get('links', []):
        href = link.get('href', '')
        text = link.get('text', '')
        if href.lower().startswith('tel:'):
            tel = href[4:].split('?')[0].strip()
            if tel:
                phones.add(tel)
        # Also scan link text
        for p in find_phones_in_text(text):
            phones.add(p)

    # 3. Meta tags
    for meta in data.get('metas', []):
        name = meta.get('name', '')
        content = meta.get('content', '')
        if any(x in name for x in ['phone', 'tel', 'contact', 'telephone']) and content:
            for p in find_phones_in_text(content):
                phones.add(p)

    # 4. JSON-LD structured data (Schema.org)
    for ld in data.get('jsonld', []):
        try:
            for p in find_phones_in_text(ld):
                phones.add(p)
        except Exception:
            pass

    return phones

# ========== SINGLE-PASS CRAWL + AUDIT ==========

async def crawl_and_audit(
    start_url: str,
    extra_urls: List[str],
    target_numbers: List[str],
    session_id: str,
    db: Session,
    max_pages: int = 500
):
    """
    Single-pass crawl + phone extraction.
    Each URL is visited ONCE: we extract phone numbers AND discover new links
    in the same page visit.  No second pass → no duplicate WAF challenges.
    """
    from urllib.parse import urlparse as _urlparse

    if start_url and not start_url.startswith(('http://', 'https://')):
        start_url = "https://" + start_url
    start_url = start_url.rstrip('/')

    base_domain = _urlparse(start_url).netloc.lower().replace("www.", "") if start_url else ""
    visited = set()
    completed_count = 0

    queue = asyncio.Queue()
    await queue.put(start_url)
    # Extra manually-supplied URLs get audited too
    for u in extra_urls:
        await queue.put(u)

    # Seed from sitemap if crawling (start_url is provided)
    if start_url:
        print(f"DEBUG: Fetching sitemap for {start_url}...", flush=True)
        sitemap_urls = await fetch_sitemap_urls(start_url)
        print(f"DEBUG: Found {len(sitemap_urls)} URLs in sitemap", flush=True)
        for su in sitemap_urls:
            if su != start_url and su not in extra_urls:
                parsed = urlparse(su)
                if base_domain in parsed.netloc and not any(su.lower().endswith(ext) for ext in SKIP_EXTS):
                    await queue.put(su)

    MAX_WORKERS = 5

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
                    # Blocking — stays alive while others await WAF challenges
                    url = await queue.get()

                    # Sentinel → stop
                    if url is None:
                        queue.task_done()
                        break

                    # Already processed
                    if url in visited:
                        queue.task_done()
                        continue

                    # Skip binary/sound downloads
                    if any(x in url for x in ['get=sound', '.mp3', '.wav']):
                        print(f"  [skip] {url}", flush=True)
                        queue.task_done()
                        continue

                    visited.add(url)
                    print(f"  [crawl+audit] {url} (Total: {len(visited)})", flush=True)

                    # ── Check session still active ──
                    local_session = local_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if not local_session or local_session.status == "stopped":
                        queue.task_done()
                        break

                    # ── Security check ──
                    if not is_safe_url(url):
                        local_db.add(models.PhoneAuditResult(
                            session_id=session_id, url=url,
                            phone_numbers=json.dumps([]), phone_count=0,
                            formats_detected=json.dumps([]),
                            issues=json.dumps(["URL blocked (Private IP)"])
                        ))
                        # Atomic update
                        local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                            models.AuditSession.completed: models.AuditSession.completed + 1,
                            models.AuditSession.total_expected: max(local_session.total_expected, len(visited))
                        })
                        await asyncio.to_thread(local_db.commit)
                        continue

                    # ── Credit deduction ──
                    try:
                        deducted, _ = check_and_deduct_credits(local_session.user_id, 1, local_db)
                        local_session.credits_used = (local_session.credits_used or 0) + deducted
                    except HTTPException:
                        local_session.status = "error: credits exhausted"
                        await asyncio.to_thread(local_db.commit)
                        queue.task_done()
                        break

                    found_data = []
                    issue_list = []

                    try:
                        # Navigate once — handles WAF/challenge internally
                        success = await navigate_page(page, url)

                        if success:
                            # ── Extract phones from the now-loaded page ──
                            raw_phones = await extract_phones_from_page(page)
                            seen_norms = set()
                            for number in raw_phones:
                                num_clean = number.strip()
                                norm = normalize_phone(num_clean)
                                if not norm or len(norm) < 7 or norm in seen_norms:
                                    continue
                                seen_norms.add(norm)
                                is_target = any(
                                    normalize_phone(t.strip()) == norm
                                    for t in target_numbers
                                ) if target_numbers else False
                                found_data.append({
                                    "number": num_clean,
                                    "location": "Body, Link, Meta, or JSON-LD",
                                    "type": "Target" if is_target else "Detected",
                                    "is_target": is_target,
                                    "valid": True,
                                    "source_text": num_clean
                                })

                            if found_data:
                                phones_str = ", ".join(d["number"] for d in found_data)
                                print(f"  [phones] {url} → {phones_str}", flush=True)

                            # ── Discover new links on the same page ──
                            try:
                                links = await page.evaluate(
                                    "Array.from(document.querySelectorAll('a')).map(e => e.href)"
                                )
                                for link in links:
                                    if not link or not isinstance(link, str):
                                        continue
                                    clean = link.split('#')[0].strip()
                                    if not clean:
                                        continue
                                    parsed = _urlparse(clean)
                                    link_netloc = parsed.netloc.lower().replace("www.", "")
                                    if link_netloc == base_domain and clean not in visited:
                                        ext = '.' + clean.rsplit('.', 1)[-1].lower() if '.' in clean.rsplit('/', 1)[-1] else ''
                                        if ext not in SKIP_EXTS and len(visited) < max_pages:
                                            await queue.put(clean)
                            except Exception as e:
                                print(f"  [link error] {url}: {e}", flush=True)
                        else:
                            issue_list.append("Navigation failed")

                    except Exception as e:
                        print(f"  [page error] {url}: {e}", flush=True)
                        issue_list.append(f"Error: {str(e)[:200]}")

                    # ── Save result ──
                    local_db.add(models.PhoneAuditResult(
                        session_id=session_id, url=url,
                        phone_numbers=json.dumps(found_data),
                        phone_count=len(found_data),
                        formats_detected=json.dumps(["Standard"]),
                        issues=json.dumps(issue_list)
                    ))
                    # Atomic update
                    local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                        models.AuditSession.completed: models.AuditSession.completed + 1,
                        models.AuditSession.total_expected: max(local_session.total_expected, len(visited))
                    })
                    await asyncio.to_thread(local_db.commit)
                    queue.task_done()

            except Exception as e:
                print(f"  [worker fatal] {e}", flush=True)
                try:
                    queue.task_done()
                except Exception:
                    pass
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    local_db.close()
                except Exception:
                    pass

        workers = [asyncio.create_task(worker()) for _ in range(MAX_WORKERS)]

        # Block until every queued item (including newly discovered URLs) is done
        await queue.join()

        # Graceful shutdown: send one sentinel per worker
        for _ in range(MAX_WORKERS):
            await queue.put(None)

        await asyncio.gather(*workers, return_exceptions=True)
        await browser.close()

    print(f"\n=== Crawl+Audit Complete: {len(visited)} pages, {completed_count} results ===", flush=True)
    return list(visited)

# ========== AUDIT TASK ==========

def phone_audit_task(urls: List[str], target_numbers: List[str], options: List[str],
                     session_id: str, user_id: int, session_name: str, crawl_url: Optional[str] = None):
    """Background task for Phone audit"""
    db = SessionLocal()
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session:
            print(f"Error: Session {session_id} not found.")
            return

        asyncio.run(audit_phone_numbers(urls, target_numbers, options, session_id, user_id, db, crawl_url))
    finally:
        db.close()


async def audit_phone_numbers(urls: List[str], target_numbers: List[str], options: List[str],
                               session_id: str, user_id: int, db: Session, crawl_url: Optional[str] = None):
    """
    Orchestrates the phone audit.
    - If crawl_url is given: single-pass crawl+audit (discover + extract in one visit).
    - If only URLs given: audit those specific URLs directly (no crawl needed).
    """
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session:
            return

        if crawl_url:
            # ── SINGLE-PASS MODE: crawl from root + audit simultaneously ──
            session.status = "crawling:Discovering & auditing pages..."
            await asyncio.to_thread(db.commit)

            await crawl_and_audit(
                start_url=crawl_url,
                extra_urls=urls,          # any manually added URLs get included
                target_numbers=target_numbers,
                session_id=session_id,
                db=db,
                max_pages=999999
            )

        else:
            # ── DIRECT MODE: audit a fixed list of URLs, no crawling ──
            session.status = "running"
            session.total_expected = len(urls)
            await asyncio.to_thread(db.commit)

            await crawl_and_audit(
                start_url=urls[0] if urls else "",
                extra_urls=urls[1:] if len(urls) > 1 else [],
                target_numbers=target_numbers,
                session_id=session_id,
                db=db,
                max_pages=len(urls)
            )

        db.expire_all()
        db.refresh(session)
        if session.status not in ("stopped", "error: credits exhausted"):
            session.status = "completed"
            session.completed_at = datetime.utcnow()
            await asyncio.to_thread(db.commit)

    except Exception as e:
        print(f"Phone Audit Fatal: {e}", flush=True)
        try:
            db.refresh(session)
            session.status = "error"
            await asyncio.to_thread(db.commit)
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass

# ========== ROUTES ==========

@router.get("/platform/phone", response_class=HTMLResponse)
async def phone_audit_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("phone_validator.html", {"request": request, "user": user})

@router.get("/phone-audit")
async def phone_audit_redirect(request: Request, user = Depends(require_auth)):
    """Redirect old URL pattern to new one"""
    return await phone_audit_page(request, user)

@router.post("/upload/phone")
async def upload_phone(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    target_numbers: Optional[str] = Form(None),
    options: str = Form("[]"),
    session_name: str = Form("My Phone Audit"),
    crawl_url: Optional[str] = Form(None),
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

    urls = list(dict.fromkeys(urls))

    try:
        low_credit_warning = check_user_credits(user.id, len(urls) if urls else 1, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = len(urls) if urls else 1

    target_num_list = []
    if target_numbers:
        target_num_list = [n.strip() for n in target_numbers.split(',') if n.strip()]

    total = len(urls) if not crawl_url else 1
    session_id = f"phn_{uuid.uuid4().hex[:8]}"

    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        name=session_name,
        session_type="phone",
        status="running",
        total_expected=total,
        completed=0,
        urls=json.dumps(urls),
        browsers=json.dumps(["Default"]),
        resolutions=json.dumps(["Default"]),
        credits_balance=user.credits
    )
    db.add(new_session)
    db.commit()

    background_tasks.add_task(phone_audit_task, urls, target_num_list, json.loads(options), session_id, user.id, session_name, crawl_url)
    running_tasks[session_id] = "phone"

    return JSONResponse({"session": session_id, "total_expected": total, "type": "phone", "low_credits": low_credit_warning})

@router.get("/phone-results/{session_id}")
async def phone_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")

    session = db.query(models.AuditSession).filter(
        models.AuditSession.session_id == session_id,
        models.AuditSession.user_id == user.id
    ).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")

    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)

    results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()

    return templates.TemplateResponse("phone_report.html", {
        "request": request, "user": user, "session": session,
        "session_id": session_id, "results": results
    })

@router.get("/results/phone/{session_id}")
async def results_phone_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await phone_results_view(session_id, request, db)
