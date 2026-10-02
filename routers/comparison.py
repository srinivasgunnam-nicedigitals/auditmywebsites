from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import os
import uuid
import datetime
from sqlalchemy.orm import Session

from database import get_db
from routers.auth import get_current_user_from_cookie
from utils.ui import templates
import json
from models import AuditSession, ContentComparisonResult
from utils.comparison import (
    fetch_html, extract_text, compare_texts, 
    generate_observations, build_diff_rows, generate_txt_report
)

router = APIRouter()

class ComparisonRequest(BaseModel):
    staging_url: str
    live_url: str

@router.get("/platform/comparison", response_class=HTMLResponse)
async def comparison_page(request: Request, user = Depends(get_current_user_from_cookie)):
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("comparison.html", {"request": request, "user": user})

@router.get("/results/comparison/{session_id}", response_class=HTMLResponse)
async def comparison_result_page(
    session_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login")
    
    # Get session and result
    session = db.query(AuditSession).filter(AuditSession.session_id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    result = db.query(ContentComparisonResult).filter(ContentComparisonResult.session_id == session_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Comparison result not found")
        
    # Reconstruct data from JSON
    diff_rows = json.loads(result.diff_rows) if result.diff_rows else []
    observations = json.loads(result.observations) if result.observations else []
    
    return templates.TemplateResponse("comparison_report.html", {
        "request": request,
        "user": user,
        "session": session,
        "result": result,
        "diff_rows": diff_rows,
        "observations": observations
    })

@router.post("/compare-urls")
async def compare_urls(
    req: ComparisonRequest, 
    request: Request,
    db: Session = Depends(get_db)
):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Check credits (cost: 5 credits for a comparison)
    if user.credits < 5:
        raise HTTPException(status_code=400, detail="Insufficient credits (5 required)")

    try:
        # Generate session ID
        session_id = str(uuid.uuid4())[:8]
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Fetch content
        staging_html = await fetch_html(req.staging_url)
        live_html = await fetch_html(req.live_url)
        
        # Fallback to playwright if content is very thin (simple JS detection)
        if len(staging_html) < 1000 or len(live_html) < 1000:
            staging_html = await fetch_html(req.staging_url, use_playwright=True)
            live_html = await fetch_html(req.live_url, use_playwright=True)

        # Extract
        staging_data = extract_text(staging_html)
        live_data = extract_text(live_html)
        
        # Compare
        summary = compare_texts(staging_data["text_lines"], live_data["text_lines"]) # staging -> live
        diff_rows = build_diff_rows(staging_data["text_lines"], live_data["text_lines"])
        
        # Metadata check
        metadata_diff = {
            "title_changed": staging_data["metadata"]["title"] != live_data["metadata"]["title"],
            "desc_changed": staging_data["metadata"]["description"] != live_data["metadata"]["description"]
        }
        
        # Observations
        observations = generate_observations(summary, metadata_diff)
        
        # Create Audit Session
        new_session = AuditSession(
            session_id=session_id,
            user_id=user.id,
            session_type="comparison",
            name=f"Comparison: {req.live_url[:30]}...",
            urls=json.dumps([req.live_url, req.staging_url]),
            browsers=json.dumps(["default"]),
            resolutions=json.dumps(["default"]),
            status="completed",
            credits_used=5,
            total_expected=1,
            completed=1,
            completed_at=datetime.datetime.utcnow(),
            credits_balance=user.credits
        )
        db.add(new_session)
        
        # Save Result
        comp_result = ContentComparisonResult(
            session_id=session_id,
            live_url=req.live_url,
            staging_url=req.staging_url,
            similarity_score=int(summary['similarity_score'] * 100),
            added_count=summary["counts"]["added"],
            removed_count=summary["counts"]["removed"],
            modified_count=summary["counts"]["modified"],
            diff_rows=json.dumps(diff_rows),
            observations=json.dumps(observations),
            metadata_diff=json.dumps(metadata_diff)
        )
        db.add(comp_result)
        
        # File Handling (keeping TXT report as a download option)
        filename_base = f"report_{timestamp_str}_{session_id}"
        reports_dir = "reports"
        os.makedirs(reports_dir, exist_ok=True)
        txt_path = os.path.join(reports_dir, f"{filename_base}.txt")
        generate_txt_report(req.staging_url, req.live_url, summary, observations, txt_path)
        
        # Deduct credits
        user.credits -= 5
        db.commit()
        
        return {
            "success": True,
            "summary": {
                "similarity": f"{int(summary['similarity_score'] * 100)}%",
                "added": summary["counts"]["added"],
                "removed": summary["counts"]["removed"],
                "modified": summary["counts"]["modified"]
            },
            "session_id": session_id,
            "report_url": f"/results/comparison/{session_id}",
            "txt_report_url": f"/reports/{filename_base}.txt"
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Comparison Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to compare URLs: {str(e)}")

