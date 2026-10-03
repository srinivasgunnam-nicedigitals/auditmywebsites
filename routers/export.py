import csv
import io
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List

import models
import database
from database import get_db
from routers.auth import require_auth

router = APIRouter(prefix="/api/export", tags=["Export"])

@router.get("/performance/{session_id}")
async def export_performance(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.PerformanceAuditResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Device", "Score", "TTFB (ms)", "FCP (ms)", "DOM Load (ms)", "Page Load (ms)", "Resources"])
    
    for r in results:
        writer.writerow([r.url, r.device_preset, r.score, r.ttfb, r.fcp, r.dom_load, r.page_load, r.resource_count])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=performance_audit_{session_id}.csv"}
    )

@router.get("/accessibility/{session_id}")
async def export_accessibility(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.AccessibilityAuditResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Score", "Total Violations", "Critical", "Serious", "Moderate", "Minor"])
    
    for r in results:
        writer.writerow([r.url, r.score, r.violations_count, r.critical_count, r.serious_count, r.moderate_count, r.minor_count])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=accessibility_audit_{session_id}.csv"}
    )

@router.get("/h1/{session_id}")
async def export_h1(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "H1 Count", "Issues"])
    
    for r in results:
        writer.writerow([r.url, r.h1_count, r.issues])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=h1_audit_{session_id}.csv"}
    )

@router.get("/phone/{session_id}")
async def export_phone(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.PhoneAuditResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Phone Number", "Type", "Source Text", "Location"])
    
    import json
    for r in results:
        numbers = []
        try:
            if r.phone_numbers:
                numbers = json.loads(r.phone_numbers)
        except json.JSONDecodeError:
            numbers = []
        
        if not numbers:
            writer.writerow([r.url, "None", "N/A", "N/A", "N/A"])
        else:
            for num in numbers:
                phone = num.get("number", "Unknown")
                p_type = num.get("type", "Unknown")
                source = num.get("source_text", "Unknown")
                location = num.get("location", "Unknown")
                writer.writerow([r.url, phone, p_type, source, location])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=phone_audit_{session_id}.csv"}
    )

@router.get("/meta-tags/{session_id}")
async def export_meta(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.MetaTagsResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Score", "Title", "Description", "Keywords", "Canonical", "Warnings"])
    
    for r in results:
        writer.writerow([r.url, r.score, r.title, r.description, r.keywords, r.canonical, r.warnings])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=meta_tags_audit_{session_id}.csv"}
    )

@router.get("/sitemap/{session_id}")
async def export_sitemap(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.SitemapResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Score", "URL Count", "Is Index", "Errors", "Warnings"])
    
    for r in results:
        writer.writerow([r.url, r.score, r.url_count, r.is_index, r.errors, r.warnings])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=sitemap_audit_{session_id}.csv"}
    )

@router.get("/image-alt/{session_id}")
async def export_image_alt(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.ImageAltResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Score", "Image Count"])
    
    for r in results:
        # Assuming we just want the count for now as images_alt is a large JSON
        import json
        try:
            images = json.loads(r.images_alt) if r.images_alt else []
            count = len(images)
        except:
            count = 0
        writer.writerow([r.url, r.score, count])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=image_alt_audit_{session_id}.csv"}
    )

@router.get("/responsive/{session_id}")
async def export_responsive(session_id: str, db: Session = Depends(get_db)):
    results = db.query(models.StaticAuditResult).filter_by(session_id=session_id).all()
    if not results:
        raise HTTPException(status_code=404, detail="No results found for this session")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["URL", "Browser", "Resolution", "Screenshot Path"])
    
    for r in results:
        writer.writerow([r.url, r.browser, r.resolution, r.screenshot_path])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=responsive_audit_{session_id}.csv"}
    )

@router.get("/static/{session_id}")
async def export_static(session_id: str, db: Session = Depends(get_db)):
    """Alias for /api/export/responsive/{session_id} — static screenshot audits."""
    return await export_responsive(session_id, db)

@router.get("/dynamic/{session_id}")
async def export_dynamic(session_id: str, db: Session = Depends(get_db)):
    """Alias for /api/export/responsive/{session_id} — dynamic video audits."""
    return await export_responsive(session_id, db)
