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

async def audit_meta_tags_logic(urls: List[str], session_id: str, crawl_data: dict = None):
    """Background task for Meta Tags audit. crawl_data contains {live_base, staging_base} if dual crawling"""
    db = SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return

        # Moderate concurrency to avoid SQLite contention
        sem = asyncio.Semaphore(10)
        
        async with httpx.AsyncClient(
            follow_redirects=True, 
            verify=False, 
            timeout=15.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=15)
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

                        max_retries = 2
                        retry_delay = 1
                        last_error = "Unknown"

                        for attempt in range(max_retries):
                            try:
                                if attempt > 0:
                                    await asyncio.sleep(retry_delay)

                                resp = await client.get(url)
                                html = resp.text
                                soup = await asyncio.to_thread(BeautifulSoup, html, "html.parser")
                                
                                title = ""
                                title_tag = soup.find("title") or soup.find("meta", attrs={"property": "og:title"})
                                if title_tag:
                                    title = title_tag.text.strip() if title_tag.name == "title" else title_tag.get("content", "").strip()
                                
                                description = ""
                                desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                                if desc_tag:
                                    description = desc_tag.get("content", "").strip()
                                
                                keywords = ""
                                kw_tag = soup.find("meta", attrs={"name": "keywords"})
                                if kw_tag: keywords = kw_tag.get("content", "").strip()
                                
                                canonical = ""
                                canon_tag = soup.find("link", rel="canonical")
                                if canon_tag: canonical = canon_tag.get("href", "").strip()
                                
                                og_tags = {}
                                for tag in soup.find_all("meta", property=re.compile(r'^og:')):
                                    og_tags[tag.get("property")] = tag.get("content", "")

                                twitter_tags = {}
                                for tag in soup.find_all("meta", attrs={"name": re.compile(r'^twitter:')}):
                                    twitter_tags[tag.get("name")] = tag.get("content", "")
                                
                                schema_tags = []
                                for script in soup.find_all("script", type="application/ld+json"):
                                    try: schema_tags.append(json.loads(script.string))
                                    except: pass
                                
                                warnings = []
                                missing_tags = []
                                score = 100
                                if not title: missing_tags.append("Title"); score -= 20
                                elif len(title) < 30 or len(title) > 60: warnings.append(f"Title length ({len(title)}) suboptimal."); score -= 5
                                if not description: missing_tags.append("Description"); score -= 20
                                elif len(description) < 70 or len(description) > 155: warnings.append(f"Description length ({len(description)}) suboptimal."); score -= 5
                                if not canonical: warnings.append("Missing Canonical URL."); score -= 10
                                if not og_tags: warnings.append("Missing OG tags."); score -= 10
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
                            fail_result = models.MetaTagsResult(
                                session_id=session_id,
                                url=url,
                                title="Scan Failed",
                                description=last_error[:255], 
                                og_tags="{}",
                                twitter_tags="{}",
                                schema_tags="[]",
                                missing_tags=json.dumps(["Critical Scan Error"]),
                                warnings=json.dumps([f"Could not access URL after {max_retries} attempts"]),
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

            # Process URLs in batches of 50 to avoid overwhelming SQLite
            batch_size = 50
            for i in range(0, len(urls), batch_size):
                batch = urls[i:i+batch_size]
                await asyncio.gather(*[process_url(u) for u in batch])
                
                # Update progress once per batch
                try:
                    prog_db = SessionLocal()
                    s_prog = prog_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if s_prog:
                        # Atomic update (this one is once per batch, but let's be safe)
                        prog_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                            models.AuditSession.completed: completed_count
                        })
                        if s_prog.status == "stopped":
                            prog_db.close()
                            break
                        await asyncio.to_thread(prog_db.commit)
                    prog_db.close()
                except: pass

            db.expire_all()
            if session:
                db.refresh(session)
                if session.status != "stopped":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                    await asyncio.to_thread(db.commit)
    except Exception as e:
        print(f"Meta tags audit failed: {e}")
        if session:
            db.refresh(session)
            session.status = "error"
            await asyncio.to_thread(db.commit)
    finally:
        db.close()

def run_meta_crawl_and_audit(urls: List[str], session_id: str, live_base: str, staging_base: str, crawl_site: bool):
    import sys
    import asyncio
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_run_meta_crawl_and_audit(urls, session_id, live_base, staging_base, crawl_site))

async def _run_meta_crawl_and_audit(urls: List[str], session_id: str, live_base: str, staging_base: str, crawl_site: bool):
    """Background task to crawl and then audit"""
    final_urls = []
    if crawl_site and live_base and staging_base:
        # Update status to crawling
        found_count = 0
        lock = asyncio.Lock()
        
        async def on_progress(n):
            nonlocal found_count
            async with lock:
                found_count += n
                # Update DB every 50 pages or at initial stages to minimize SQLite writes
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
            
            # Start crawls in parallel — each crawler has its own internal time limit
            live_task = discover_urls(live_base, max_pages=2000, max_time=600, progress_callback=on_progress)
            staging_task = discover_urls(staging_base, max_pages=2000, max_time=600, progress_callback=on_progress)
            
            live_pages, staging_pages = await asyncio.gather(live_task, staging_task)
            
            # Match pages by relative path
            paths = set()
            for p in live_pages: paths.add(get_relative_path(p, live_base))
            for p in staging_pages: paths.add(get_relative_path(p, staging_base))
            
            for rel_path in sorted(list(paths)):
                final_urls.append(urljoin(live_base, rel_path.lstrip('/')))
                final_urls.append(urljoin(staging_base, rel_path.lstrip('/')))
            
            if s:
                s.urls = json.dumps(final_urls)
                s.total_expected = len(final_urls)
                s.status = "running"
                await asyncio.to_thread(db.commit)
        finally:
            db.close()
    elif crawl_site and urls:
        # Single URL Crawl Mode (or multiple manual URLs)
        # We need to discover pages for each provided URL
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
            
            # If nothing discovered (e.g. single page or failure), keep original
            if not discovered_urls:
                final_urls = urls
            else:
                final_urls = sorted(list(discovered_urls))

            if s:
                s.urls = json.dumps(final_urls)
                s.total_expected = len(final_urls)
                s.completed = 0  # Reset counter — crawl phase done, audit phase starting
                s.status = "running"
                await asyncio.to_thread(db.commit)
        finally:
            db.close()
    else:
        final_urls = urls

    await audit_meta_tags_logic(final_urls, session_id)

# ========== ROUTES ==========

@router.get("/platform/meta-tags/compare", response_class=HTMLResponse)
async def meta_tags_compare_single(
    request: Request, 
    live_id: int, 
    staging_id: int, 
    user = Depends(require_auth),
    db: Session = Depends(get_db)
):
    live_result = db.query(models.MetaTagsResult).filter(models.MetaTagsResult.id == live_id).first()
    staging_result = db.query(models.MetaTagsResult).filter(models.MetaTagsResult.id == staging_id).first()
    
    if not live_result or not staging_result:
        return HTMLResponse("<h1>Error: Meta tag results not found.</h1>", status_code=404)

    # Use live URL path as title
    path = urlparse(live_result.url).path

    return templates.TemplateResponse("meta_single_compare.html", {
        "request": request,
        "user": user,
        "live_result": live_result,
        "staging_result": staging_result,
        "path": path
    })

@router.get("/platform/meta-tags", response_class=HTMLResponse)
async def meta_tags_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("metatags.html", {"request": request, "user": user})

@router.get("/scan/meta-tags")
async def meta_tags_scan_redirect(request: Request, user = Depends(require_auth)):
    """Backward compatibility for meta-tags scan page"""
    return await meta_tags_page(request, user)

@router.post("/upload/meta-tags")
async def upload_meta_tags(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    live_url: Optional[str] = Form(None),
    staging_url: Optional[str] = Form(None),
    crawl_site: Optional[str] = Form(None),
    session_name: str = Form("My Meta Tags Scan"),
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

    # Credit deduction (1 per input URL, 1 for crawl initiation if no URLs)
    # If crawling, we charge for the seed URLs (live_url, staging_url) plus any manual/file ones.
    total_credits = len(urls)
    # If no URLs but is_crawling, it's an error in validation above, but let's be safe
    if total_credits == 0 and is_crawling: total_credits = 1 

    try:
        low_credit_warning = check_user_credits(user.id, total_credits, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = total_credits

    urls = list(dict.fromkeys(urls))

    session_id = f"meta_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="meta-tags",
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
    
    background_tasks.add_task(run_meta_crawl_and_audit, urls, session_id, live_url, staging_url, is_crawling)
    running_tasks[session_id] = "meta-tags"
    
    return JSONResponse({"session": session_id, "total_expected": len(urls) if not is_crawling else 1, "type": "meta-tags", "low_credits": low_credit_warning})

@router.get("/meta-results/{session_id}")
async def meta_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    
    results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
    
    # Check for comparison logic
    urls = json.loads(session.urls)
    
    # Calculate unique domains (netlocs) to determine if this is a comparison or a single-site crawl
    unique_domains = set()
    for u in urls:
        try:
            netloc = urlparse(u).netloc
            # Normalize www. to base domain to treat www.example.com and example.com as same site?
            # For now, let's keep it strict or loose? 
            # If user compares www vs non-www, that IS a comparison.
            # If user crawls one site, all pages have same netloc.
            netloc = netloc.replace("www.", "")
            unique_domains.add(netloc)
        except: pass
        
    # It is a comparison if there are exactly 2 distinct domains involved OR exactly 2 URLs (explicit comparison)
    # If 1 domain: Single Site Audit
    # If > 2 domains: Bulk Audit (List View)
    is_comparison = len(unique_domains) == 2 or len(urls) == 2
    
    paired_results = []
    if is_comparison:
        # Heuristic: Group by Netloc to find the two environments
        from collections import defaultdict
        grouped_urls = defaultdict(list)
        by_path = {} # Initialize here to avoid NameError
        
        for r in results:
            parsed = urlparse(r.url)
            # Use netloc as key (ignoring scheme for grouping, though usually scheme matches)
            grouped_urls[parsed.netloc].append(r.url)
            
        # If we have exactly 2 domains, we can proceed with comparison
        if len(grouped_urls) == 2:
            domains = list(grouped_urls.keys())
            
            # Determine which is Live and which is Staging
            # We can try to match against user input fields if available, but they aren't stored in session explicitly as separate fields
            # However, the 'urls' JSON in session might give a hint if it was strictly [live, staging]
            # But since that might be overwritten, we'll use the "first domain seen" heuristic from the session URL list if possible
            
            # Helper to find common prefix (base path) for a list of URLs
            def get_common_base(url_list):
                if not url_list: return ""
                # We assume they all share scheme/netloc
                s0 = url_list[0]
                parsed0 = urlparse(s0)
                base_host = f"{parsed0.scheme}://{parsed0.netloc}"
                
                paths = [urlparse(u).path for u in url_list]
                common = os.path.commonprefix(paths)
                
                # If common prefix doesn't end in /, trim to last /
                if not common.endswith('/') and '/' in common:
                    common = common.rsplit('/', 1)[0] + '/'
                elif not common.endswith('/') and not '.' in common:
                     # It might be a directory without trailing slash? Rare in this context.
                     # If it's just "/", that's fine.
                     pass
                     
                return base_host + common

            # Calculate bases
            base1 = get_common_base(grouped_urls[domains[0]])
            base2 = get_common_base(grouped_urls[domains[1]])
            
            # Assign Live/Staging
            # We'll treat the first domain in our sorted keys or list as Live for consistency if we can't tell
            # Or check against input URLs if session.urls was [live_start, staging_start, ...]
            # Let's check session URLs.
            input_urls = json.loads(session.urls) if session.urls else []
            live_root = base1
            staging_root = base2
            
            # If input_urls exists, try to match
            if input_urls:
                first_input_netloc = urlparse(input_urls[0]).netloc
                if first_input_netloc == domains[1]:
                    # Swap
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
            # Explicit 2-URL comparison (e.g. same domain)
            # Treat first URL as Live, second as Staging
            live_url = urls[0]
            staging_url = urls[1]
            
            # Use path of live_url for the key
            path = urlparse(live_url).path
            if not path: path = "/"
            
            by_path[path] = {}
            
            # Find the results objects
            live_res = next((r for r in results if r.url == live_url), None)
            staging_res = next((r for r in results if r.url == staging_url), None)
            
            if live_res: by_path[path]['live'] = live_res
            if staging_res: by_path[path]['staging'] = staging_res
        else:
            # Fallback for when 2 domains aren't clearly found (e.g. 1 domain or >2)
            # Default to simple path extraction
            for r in results:
                path = urlparse(r.url).path
                if path not in by_path: by_path[path] = {}
                by_path[path]['live'] = r
        
        # Build pairs
        # Build pairs
        for path in sorted(by_path.keys()):
            live_res = by_path[path].get('live')
            staging_res = by_path[path].get('staging')
            
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

            paired_results.append({
                'path': path,
                'live': result_to_dict(live_res),
                'staging': result_to_dict(staging_res)
            })

    return templates.TemplateResponse("meta_report.html", {
        "request": request, 
        "user": user, 
        "session": session, 
        "session_id": session_id, 
        "results": results,
        "is_site_comparison": is_comparison,
        "paired_results": paired_results,
        "paired_results": paired_results,
        "live_url": urls[0] if urls else "",
        "staging_url": "" # We don't really know the staging url in this generic view easily without the calc above
    })

@router.get("/api/results/meta-tags/{session_id}")
async def get_meta_results(session_id: str, request: Request, db: Session = Depends(get_db)):
    """API endpoint to get meta tags audit results as JSON"""
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
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
        "score": r.score
    } for r in results]}

@router.get("/results/meta-tags/{session_id}")
async def results_meta_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await meta_results_view(session_id, request, db)
