import os
import json
import asyncio
import uuid
import re
import urllib.parse
import shutil
import concurrent.futures
from datetime import datetime
from typing import List, Tuple, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from playwright.async_api import async_playwright
from PIL import Image, ImageDraw, ImageFont
import numpy as np

import models
import auth
from database import get_db, SessionLocal
from config import settings
from utils.common import get_unique_filename
from utils.ui import templates
from utils.tasks import running_tasks
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits

router = APIRouter()

# Create a process pool for heavy CPU/IO tasks
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# ========== HELPER FUNCTIONS ==========

def add_browser_frame(img_path: str, url: str):
    """Add browser frame with URL bar to screenshot."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        with Image.open(img_path) as img:
            w, h = img.size
            frame_height = 80
            new_img = Image.new('RGB', (w, h + frame_height), (240, 240, 240))
            new_img.paste(img, (0, frame_height))
            
            draw = ImageDraw.Draw(new_img)
            draw.rectangle([0, 0, w, frame_height], fill=(230, 230, 235))
            
            # Browser buttons
            draw.ellipse([15, 30, 30, 45], fill=(255, 95, 87))
            draw.ellipse([40, 30, 55, 45], fill=(255, 189, 46))
            draw.ellipse([65, 30, 80, 45], fill=(39, 201, 63))
            
            # URL Bar
            bar_x1, bar_y1, bar_x2, bar_y2 = 100, 20, w - 20, 55
            draw.rounded_rectangle([bar_x1, bar_y1, bar_x2, bar_y2], radius=18, fill=(255, 255, 255), outline=(200, 200, 200))
            
            # URL Text
            try:
                font = ImageFont.truetype("arial.ttf", 18)
            except:
                font = ImageFont.load_default()
                
            display_url = url[:80] + "..." if len(url) > 80 else url
            draw.text((120, 28), display_url, fill=(100, 100, 100), font=font)
            
            new_img.save(img_path)
    except Exception as e:
        print(f"Frame Error: {e}")

async def record_fullpage_video(page, url: str, w: int, h: int, session_folder: str, browser_name: str, unique_name: str, skip_goto: bool = False):
    """Record a full-page video with scrolling and mouse movement."""
    import imageio
    import numpy as np
    import io
    
    video_filename = f"{unique_name}__{w}x{h}.mp4"
    browser_folder = f"{session_folder}/{browser_name}"
    os.makedirs(browser_folder, exist_ok=True)
    video_path = f"{browser_folder}/{video_filename}"
    
    frames = []
    fps = 10
    duration_sec = 8
    
    if not skip_goto:
        try:
            await page.goto(url, wait_until="load", timeout=90000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except:
                pass
        except Exception as e:
            print(f"Video navigation error for {url}: {e}")
            return None
    
    await page.set_viewport_size({"width": w, "height": h})
    await page.wait_for_timeout(1000)
    
    # Get total page height
    total_height = await page.evaluate("document.body.scrollHeight")
    viewport_height = h
    
    # Calculate scroll steps
    total_frames = duration_sec * fps
    scroll_steps = total_height - viewport_height
    step_per_frame = scroll_steps / total_frames if scroll_steps > 0 else 0

    for i in range(total_frames):
        # Capture frame
        screenshot_bytes = await page.screenshot(type="png", full_page=False)
        img = Image.open(io.BytesIO(screenshot_bytes))
        frames.append(np.array(img))
        
        # Scroll down
        if scroll_steps > 0:
            await page.evaluate(f"window.scrollBy(0, {step_per_frame})")
        
        await asyncio.sleep(1/fps)

    # Save video
    imageio.mimsave(video_path, frames, fps=fps, quality=7)
    return video_path

# ========== AUDIT FUNCTIONS ==========

async def capture_screenshots(urls: List[str], browsers: List[str], resolutions: List[Tuple[int, int]], session_id: str, user_id: str, db: Session, access_token: str = None):
    session_folder = f"screenshots/{session_id}"
    os.makedirs(session_folder, exist_ok=True)
    
    config = {
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

            sem = asyncio.Semaphore(5)


            async def process_url(page, url, resolutions, browser_name):
                unique = get_unique_filename(url)
                db_new = SessionLocal()
                try:
                    session = db_new.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped":
                        return

                    # Initial load with the first resolution
                    init_w, init_h = resolutions[0]
                    await page.set_viewport_size({"width": init_w, "height": init_h})

                    navigation_success = False
                    max_attempts = 3
                    for attempt in range(max_attempts):
                        try:
                            response = await page.goto(url, wait_until="load", timeout=90000)
                            # Challenge detection for staging URLs
                            is_staging = any(x in url.lower() for x in ["staging", "stagging", "preview", "ourwebsitepreview"])
                            if is_staging and response and (response.status == 202 or "sg-captcha" in response.headers):
                                print(f"  [challenge] Staging URL challenge on {url}, waiting 15s...", flush=True)
                                await page.wait_for_timeout(15000)
                            else:
                                try:
                                    await page.wait_for_load_state("networkidle", timeout=10000)
                                except:
                                    pass
                                await page.wait_for_timeout(3000)
                            navigation_success = True
                            break
                        except Exception as nav_err:
                            if attempt == max_attempts - 1: raise nav_err
                            await page.wait_for_timeout(2000)
                    if not navigation_success:
                        return

                    # Scroll to trigger lazy loading
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
                            }, 150);
                        });
                    }""")
                    
                    await page.wait_for_timeout(2000)
                    await page.evaluate("() => window.scrollTo(0, 0)")
                    await page.wait_for_timeout(1000)

                    # Now loop through all resolutions for this URL
                    for w, h in resolutions:
                        # Check if session stopped between resolutions
                        session = db_new.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if session and session.status == "stopped":
                            break

                        await page.set_viewport_size({"width": w, "height": h})
                        await page.wait_for_timeout(500) # Wait for layout to settle after resize

                        path = f"{session_folder}/{browser_name}/{unique}__{w}x{h}.png"
                        
                        if browser_name.lower() == "safari":
                            try:
                                await page.screenshot(path=path, full_page=True, timeout=30000)
                            except:
                                await page.screenshot(path=path, full_page=False, timeout=15000)
                        else:
                            await page.screenshot(path=path, full_page=True)

                        # Optimize to WebP
                        upload_path = path
                        upload_filename = os.path.basename(path)
                        
                        try:
                            webp_path = path.replace(".png", ".webp")
                            with Image.open(path) as img:
                                img.save(webp_path, "WEBP", quality=80, optimize=True)
                            if os.path.exists(webp_path):
                                os.remove(path)
                                upload_path = webp_path
                                upload_filename = os.path.basename(webp_path)
                        except:
                            pass

                        # Add frame
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(executor, add_browser_frame, upload_path, url)

                        # Update DB
                        try:
                            screenshot_path = f"/screenshots/{session_id}/{browser_name}/{upload_filename}"
                            result_record = models.StaticAuditResult(
                                session_id=session_id,
                                url=url,
                                browser=browser_name.title(),
                                resolution=f"{w}x{h}",
                                screenshot_path=screenshot_path,
                                filename=upload_filename
                            )
                            db_new.add(result_record)
                            
                            # Atomic increment to avoid race conditions with multiple workers
                            db_new.query(models.AuditSession).filter_by(session_id=session_id).update({
                                models.AuditSession.completed: models.AuditSession.completed + 1
                            })
                            await asyncio.to_thread(db_new.commit)
                        except Exception as e:
                            print(f"DB Error processing {url} ({w}x{h}): {e}")

                except Exception as e:
                    print(f"Error processing {url}: {e}")
                finally:
                    db_new.close()

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                launch_args = {"headless": True}
                if browser_name == "Chrome": launch_args["channel"] = "chrome"
                elif browser_name == "Edge": launch_args["channel"] = "msedge"

                try:
                    browser = await browser_map[browser_name].launch(**launch_args)
                except:
                    return

                context_args = {
                    "viewport": {"width": 1280, "height": 720},
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                }
                if browser_name.lower() == "safari":
                    context_args.update({
                        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                        "bypass_csp": True,
                        "ignore_https_errors": True
                    })
                
                context = await browser.new_context(**context_args)
                
                async def worker(url):
                    async with sem:
                        page = await context.new_page()
                        await process_url(page, url, resolutions, browser_name)
                        await page.close()

                tasks = [worker(url) for url in urls]
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(b) for b in browsers])

            db.expire_all()
            session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if session and session.status != "stopped":
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                await asyncio.to_thread(db.commit)
            
    except Exception as e:
        print(f"Static audit error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            await asyncio.to_thread(db.commit)
    
    if session_id in running_tasks:
        del running_tasks[session_id]

async def record_videos_async(urls: List[str], selected_browsers: List[str], 
                              selected_resolutions: List[Tuple[int, int]], 
                              session_id: str, user_id: str, db: Session, access_token: str = None):
    session_folder = f"videos/{session_id}"
    os.makedirs(session_folder, exist_ok=True)

    try:
        async with async_playwright() as p:
            browser_map = {"Chrome": p.chromium, "Edge": p.chromium}
            sem = asyncio.Semaphore(3)
            
            async def process_video(page, url, resolutions, browser_name, unique_name):
                local_db = SessionLocal()
                try:
                    session = local_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                    if session and session.status == "stopped": return

                    # Multi-resolution optimization: Navigate once
                    try:
                        await page.goto(url, wait_until="load", timeout=90000)
                        try:
                            await page.wait_for_load_state("networkidle", timeout=10000)
                        except:
                            pass
                        await page.wait_for_timeout(2000)
                    except Exception as nav_e:
                        print(f"Video navigation fatal error for {url}: {nav_e}")
                        local_db.close()
                        return

                    # Challenge detection for staging URLs (optional but good for consistency)
                    is_staging = any(x in url.lower() for x in ["staging", "stagging", "preview", "ourwebsitepreview"])
                    # Check status from the goto response if possible, but here we just rely on networkidle
                    
                    for w, h in resolutions:
                        # Check stopped
                        session = local_db.query(models.AuditSession).filter_by(session_id=session_id).first()
                        if session and session.status == "stopped": break

                        video_path_local = await record_fullpage_video(page, url, w, h, session_folder, browser_name, unique_name, skip_goto=True)
                        video_url = f"/videos/{session_id}/{browser_name}/{os.path.basename(video_path_local)}"
                        
                        result = models.DynamicAuditResult(
                            session_id=session_id,
                            url=url,
                            browser=browser_name,
                            resolution=f"{w}x{h}",
                            video_path=video_url,
                            filename=os.path.basename(video_path_local)
                        )
                        local_db.add(result)
                        
                        # Atomic increment
                        local_db.query(models.AuditSession).filter_by(session_id=session_id).update({
                            models.AuditSession.completed: models.AuditSession.completed + 1
                        })
                        await asyncio.to_thread(local_db.commit)
                except Exception as e:
                    print(f"Video Error for {url}: {e}")
                finally:
                    local_db.close()

            async def run_browser(browser_name: str):
                os.makedirs(f"{session_folder}/{browser_name}", exist_ok=True)
                launch_args = {"headless": True, "channel": "chrome" if browser_name == "Chrome" else "msedge"}
                browser = await browser_map[browser_name].launch(**launch_args)
                context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
                
                async def worker(url):
                    async with sem:
                        page = await context.new_page()
                        unique = get_unique_filename(url)
                        await process_video(page, url, selected_resolutions, browser_name, unique)
                        await page.close()

                tasks = [worker(url) for url in urls]
                await asyncio.gather(*tasks)
                await context.close()
                await browser.close()

            await asyncio.gather(*[run_browser(b) for b in selected_browsers])

            db.expire_all()
            session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
            if session and session.status != "stopped":
                session.status = "completed"
                session.completed_at = datetime.utcnow()
                await asyncio.to_thread(db.commit)
    except Exception as e:
        print(f"Dynamic Audit Error: {e}")
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if session:
            session.status = "error"
            await asyncio.to_thread(db.commit)
    
    if session_id in running_tasks:
        del running_tasks[session_id]

# ========== BACKGROUND TASKS ==========

def static_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], session_id: str, user_id: str, session_name: str, access_token: str = None):
    db = SessionLocal()
    try:
        # Session record should already exist from the endpoint
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session:
            print(f"Error: Session {session_id} not found in background task.")
            return

        # Parse resolutions
        res_tuples = []
        for r in resolutions:
            try:
                w, h = map(int, r.split("x"))
                res_tuples.append((w, h))
            except ValueError:
                continue

        # Run the audit
        asyncio.run(capture_screenshots(urls, browsers, res_tuples, session_id, user_id, db, access_token))
    finally:
        db.close()

def dynamic_audit_task(urls: List[str], browsers: List[str], resolutions: List[str], session_id: str, user_id: str, session_name: str, access_token: str = None):
    db = SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session:
            print(f"Error: Session {session_id} not found in background task.")
            return

        res_tuples = []
        for r in resolutions:
            try:
                w, h = map(int, r.split("x"))
                res_tuples.append((w, h))
            except ValueError:
                continue

        asyncio.run(record_videos_async(urls, browsers, res_tuples, session_id, user_id, db, access_token))
    finally:
        db.close()

# ========== ROUTES ==========

@router.get("/responsive", response_class=HTMLResponse)
async def responsive_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("static_snapshots.html", {"request": request, "user": user})

@router.get("/responsive/static", response_class=HTMLResponse)
async def static_audit_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("static.html", {"request": request, "user": user})

@router.get("/responsive/dynamic", response_class=HTMLResponse)
async def dynamic_audit_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@router.get("/platform/static", response_class=HTMLResponse)
async def static_audit_platform(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("static.html", {
        "request": request, 
        "user": user,
        "show_nav": True
    })

@router.post("/upload/static")
async def upload_static(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Responsive Audit"),
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
    
    if not urls: return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)
    if not selected_browsers or not selected_resolutions:
        return JSONResponse({"error": "Select at least one browser and resolution"}, status_code=400)

    # Credit deduction - 1 credit per (URL * Browser * Resolution)
    try:
        charge_amount = len(urls) * len(selected_browsers) * len(selected_resolutions)
        _, low_credit_warning = check_and_deduct_credits(user.id, charge_amount, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = charge_amount

    urls = list(dict.fromkeys(urls))

    # Generate unique session ID: res_ + 8 hex chars
    session_id = f"res_{uuid.uuid4().hex[:8]}"
    total_tasks = len(urls) * len(selected_browsers) * len(selected_resolutions)
    
    # Create session record in foreground to avoid race conditions
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        name=session_name,
        session_type="static",
        status="running",
        credits_used=charge_amount,
        total_expected=total_tasks,
        completed=0,
        urls=json.dumps(urls),
        browsers=json.dumps(selected_browsers),
        resolutions=json.dumps(selected_resolutions),
        credits_balance=user.credits
    )
    db.add(new_session)
    db.commit()

    token = request.cookies.get("access_token")
    background_tasks.add_task(static_audit_task, urls, selected_browsers, selected_resolutions, session_id, user.id, session_name, token)
    running_tasks[session_id] = "static"

    return JSONResponse({"session": session_id, "total_expected": total_tasks, "type": "static", "low_credits": low_credit_warning})

@router.post("/upload/dynamic")
async def upload_dynamic(
    request: Request,
    file: Optional[UploadFile] = File(None),
    manual_urls: Optional[str] = Form(None),
    browsers: str = Form(...),
    resolutions: str = Form(...),
    session_name: str = Form("My Dynamic Audit"),
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
    
    if not urls: return JSONResponse({"error": "No valid URLs found"}, status_code=400)

    selected_browsers = json.loads(browsers)
    selected_resolutions = json.loads(resolutions)
    supported_browsers = [b for b in selected_browsers if b in ["Chrome", "Edge"]]
    if not supported_browsers: return JSONResponse({"error": "Select Chrome or Edge for video recording"}, status_code=400)
    if not selected_resolutions: return JSONResponse({"error": "Select at least one resolution"}, status_code=400)

    # Credit deduction - 1 credit per (URL * Browser * Resolution)
    try:
        charge_amount = len(urls) * len(supported_browsers) * len(selected_resolutions)
        _, low_credit_warning = check_and_deduct_credits(user.id, charge_amount, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = charge_amount

    urls = list(dict.fromkeys(urls))

    # Generate unique session ID: dyn_ + 8 hex chars
    session_id = f"dyn_{uuid.uuid4().hex[:8]}"
    total_tasks = len(urls) * len(supported_browsers) * len(selected_resolutions)

    # Create session record in foreground
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        name=session_name,
        session_type="dynamic",
        status="running",
        credits_used=charge_amount,
        total_expected=total_tasks,
        completed=0,
        urls=json.dumps(urls),
        browsers=json.dumps(supported_browsers),
        resolutions=json.dumps(selected_resolutions),
        credits_balance=user.credits
    )
    db.add(new_session)
    db.commit()

    token = request.cookies.get("access_token")

    background_tasks.add_task(dynamic_audit_task, urls, supported_browsers, selected_resolutions, session_id, user.id, session_name, token)
    running_tasks[session_id] = "dynamic"

    return JSONResponse({"session": session_id, "total_expected": total_tasks, "type": "dynamic", "low_credits": low_credit_warning})

@router.get("/static-results/{session_id}")
async def static_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")
        
    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)
        
    try:
        session.urls = json.loads(session.urls)
        session.browsers = json.loads(session.browsers)
        session.resolutions = json.loads(session.resolutions)
    except: pass
        
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    results_list = [{"url": r.url, "browser": r.browser, "resolution": r.resolution, "filename": r.filename, "screenshot_path": r.screenshot_path} for r in results]
    
    import time
    return templates.TemplateResponse("static_report.html", {
        "request": request, 
        "user": user, 
        "session": session, 
        "session_id": session_id,  # Add session_id for template
        "results": results,
        "results_data": json.dumps(results_list), 
        "results_json": json.dumps([r.url for r in results]),
        "cache_buster": int(time.time())
    })

@router.get("/dynamic-results/{session_id}")
async def dynamic_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        if isinstance(session.urls, str): session.urls = json.loads(session.urls)
        if isinstance(session.browsers, str): session.browsers = json.loads(session.browsers)
        if isinstance(session.resolutions, str): session.resolutions = json.loads(session.resolutions)
    except: pass

    results = db.query(models.DynamicAuditResult).filter_by(session_id=session_id).all()
    results_list = [{"url": r.url, "browser": r.browser, "resolution": r.resolution, "video_path": r.video_path, "filename": r.filename} for r in results]

    return templates.TemplateResponse("dynamic-results.html", {
        "request": request, "user": user, "session": session, "results": results, "results_json": json.dumps(results_list)
    })

# Backward compatibility routes
@router.get("/results/static/{session_id}")
async def results_static_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await static_results_view(session_id, request, db)

@router.get("/results/dynamic/{session_id}")
async def results_dynamic_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await dynamic_results_view(session_id, request, db)

@router.get("/results/static/{session_id}/snapshots")
async def static_snapshots_view(session_id: str, url: str, browser: str, request: Request, db: Session = Depends(get_db)):
    """View detailed snapshots for a specific URL and browser - requires authentication"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login")
    
    session = db.query(models.AuditSession).filter_by(session_id=session_id, user_id=user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)
    
    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)
        
    # Parse session data
    try:
        session.urls = json.loads(session.urls) if isinstance(session.urls, str) else session.urls
        session.browsers = json.loads(session.browsers) if isinstance(session.browsers, str) else session.browsers
        session.resolutions = json.loads(session.resolutions) if isinstance(session.resolutions, str) else session.resolutions
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
