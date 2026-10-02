import os
import sys
import json
import asyncio
import uuid
import concurrent.futures
from datetime import datetime
from typing import List, Optional
from PIL import Image

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, File, UploadFile, BackgroundTasks
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
from utils import dom_diff
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits
from utils.common import get_unique_filename

router = APIRouter()

# Thread pool executor for blocking operations
executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# ========== VISUAL AUDIT LOGIC ==========

async def compare_images_logic(base_url: str, compare_url: str, session_id: str):
    """Visual comparison audit using DOM diffing and pixel comparison"""
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

def process_image_diff(base_path, compare_path, session_folder, session_id, base_url, compare_url):
    """Process pixel-level image comparison in a thread"""
    db = SessionLocal()
    
    try:
        img1 = Image.open(base_path).convert("RGB")
        img2 = Image.open(compare_path).convert("RGB")
        
        # Resize to match smallest dimensions
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
                if diff > 15:
                    diff_pixels[x, y] = (255, 0, 0)
                    diff_count += 1
                else:
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
        print(f"Image Diff Error: {e}")
        if session:
            session.status = "error"
            db.commit()
    finally:
        db.close()

# ========== ROUTES ==========

@router.post("/api/visual-test")
async def trigger_visual_test(
    request: Request,
    background_tasks: BackgroundTasks, 
    base_url: str = Form(...), 
    compare_url: str = Form(...), 
    user: models.User = Depends(require_auth), 
    db: Session = Depends(get_db)
):
    """Trigger a visual comparison audit"""
    # Credit deduction (2 URLs = 2 credits)
    try:
        _, low_credit_warning = check_and_deduct_credits(user.id, 2, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = 2

    session_id = f"vis_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="visual",
        name=f"Visual: {get_unique_filename(base_url)}",
        urls=json.dumps([base_url, compare_url]),
        browsers=json.dumps(["Chrome"]),
        resolutions=json.dumps(["1280x800"]),
        credits_used=2,
        total_expected=1
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(compare_images_logic, base_url, compare_url, session_id)
    running_tasks[session_id] = "visual"
    
    return JSONResponse({
        "status": "started",
        "session_id": session_id,
        "message": "Visual audit started",
        "low_credits": low_credit_warning
    })

@router.get('/scan/keyword-rank', response_class=HTMLResponse)
async def keyword_rank_page(request: Request, user: models.User = Depends(require_auth)):
    """Keyword rank tracking page"""
    return templates.TemplateResponse('keyword_rank.html', {'request': request, 'user': user})
