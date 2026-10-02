import httpx
import asyncio
from bs4 import BeautifulSoup
import difflib
from difflib import SequenceMatcher
import uuid
import os
import time
from datetime import datetime
from jinja2 import Template, Environment
from playwright.async_api import async_playwright

# Headers to use for fetching
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}

async def fetch_html(url: str, use_playwright: bool = False) -> str:
    """Fetch HTML content using httpx or Playwright as fallback."""
    if use_playwright:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=DEFAULT_HEADERS["User-Agent"])
            page = await context.new_page()
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                # Wait a bit more for dynamic content
                await asyncio.sleep(2)
                content = await page.content()
                return content
            finally:
                await browser.close()
    
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
        response = await client.get(url, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        return response.text

def _clean_soup(soup):
    """Remove invisible/non-content tags from a soup, in-place."""
    for tag in soup(['script', 'style', 'noscript', 'svg', 'iframe']):
        tag.decompose()
    # Remove screen reader / accessibility-only spans
    for el in soup.find_all(True):
        class_str = ' '.join(el.get('class', [])).lower()
        if any(cls in class_str for cls in ['sr-only', 'screen-reader-text', 'skip-link', 'visually-hidden']):
            el.decompose()

def _section_lines(el) -> list:
    """Extract non-empty text lines from a BeautifulSoup element."""
    if not el:
        return []
    text = el.get_text(separator='\n')
    return [line.strip() for line in text.splitlines() if line.strip()]

def extract_text(html: str) -> dict:
    """Extract visible text divided into header / main / footer sections."""
    soup = BeautifulSoup(html, 'html.parser')

    # ── metadata ──────────────────────────────────────────────────────────────
    metadata = {
        "title": soup.title.string.strip() if soup.title else "No Title",
        "description": "",
        "h1": [h.get_text(strip=True) for h in soup.find_all('h1')]
    }
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc:
        metadata["description"] = meta_desc.get('content', '').strip()

    # ── clean invisible elements ───────────────────────────────────────────────
    _clean_soup(soup)

    # ── locate semantic sections ───────────────────────────────────────────────
    header_el  = soup.find('header') or soup.find(attrs={'role': 'banner'})
    footer_el  = soup.find('footer') or soup.find(attrs={'role': 'contentinfo'})
    main_el    = (soup.find('main')
                  or soup.find(attrs={'role': 'main'})
                  or soup.find('article')
                  or soup.body)

    # ── build flat list with section banners ───────────────────────────────────
    text_lines: list[str] = []

    for label, el in [
        ("── HEADER ──", header_el),
        ("── MAIN ──",   main_el),
        ("── FOOTER ──", footer_el),
    ]:
        lines = _section_lines(el)
        if lines:
            text_lines.append(label)
            text_lines.extend(lines)

    # fallback: if nothing was found, dump whole body
    if not text_lines and soup.body:
        text_lines = _section_lines(soup.body)

    return {"text_lines": text_lines, "metadata": metadata}

def compare_texts(lines1: list, lines2: list):
    """Compare two lists of text lines and categorize differences."""
    matcher = SequenceMatcher(None, lines1, lines2)
    similarity = matcher.ratio()
    
    diff = list(difflib.ndiff(lines1, lines2))
    
    added = []
    removed = []
    modified = []
    
    i = 0
    while i < len(diff):
        line = diff[i]
        if line.startswith('- '):
            if i + 1 < len(diff) and diff[i+1].startswith('+ '):
                s = SequenceMatcher(None, line[2:], diff[i+1][2:]).ratio()
                if s > 0.4:
                    modified.append({"old": line[2:], "new": diff[i+1][2:], "similarity": s})
                    i += 2
                    continue
            removed.append(line[2:])
        elif line.startswith('+ '):
            added.append(line[2:])
        i += 1
            
    return {
        "similarity_score": similarity,
        "added": added,
        "removed": removed,
        "modified": modified,
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified)
        }
    }

def generate_observations(summary: dict, metadata_diff: dict) -> list:
    """Generate intelligent insights based on the comparison."""
    observations = []
    if summary["similarity_score"] < 0.3:
        observations.append("⚠️ Major content overhaul detected.")
    elif summary["similarity_score"] < 0.7:
        observations.append("📝 Moderate rewriting detected.")
    elif summary["similarity_score"] < 0.98:
        observations.append("🔍 Minor content updates detected.")
    else:
        observations.append("✅ Content is nearly identical.")

    all_added_text = " ".join(summary["added"]).lower()
    all_removed_text = " ".join(summary["removed"]).lower()
    
    pricing_keywords = ["price", "cost", "dollar", "$", "subscription", "plan", "pricing"]
    if any(k in all_added_text for k in pricing_keywords) or any(k in all_removed_text for k in pricing_keywords):
        observations.append("💰 Pricing-related changes detected.")

    if metadata_diff["title_changed"]:
        observations.append("📊 Page Title changed.")
    if metadata_diff["desc_changed"]:
        observations.append("📄 Meta Description updated.")
        
    if not observations:
        observations.append("No significant patterns identified.")
    return observations

def build_diff_rows(lines1: list, lines2: list):
    """Generate rows for side-by-side comparison with intelligent block-local alignment."""
    matcher = SequenceMatcher(None, lines1, lines2)
    rows = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                rows.append({
                    "left_no": i + 1, "left_text": lines1[i],
                    "right_no": j + 1, "right_text": lines2[j],
                    "type": "equal"
                })
        elif tag == 'replace':
            # Sub-align within the replaced block
            b1, b2 = lines1[i1:i2], lines2[j1:j2]
            # Use ndiff for the sub-block to get better alignment hints
            sub_diff = list(difflib.ndiff(b1, b2))
            
            idx = 0
            l_off, r_off = 0, 0
            while idx < len(sub_diff):
                line = sub_diff[idx]
                tag_sub = line[:2]
                content = line[2:]
                
                if tag_sub == '  ': # Equal
                    rows.append({
                        "left_no": i1 + l_off + 1, "left_text": b1[l_off],
                        "right_no": j1 + r_off + 1, "right_text": b2[r_off],
                        "type": "equal"
                    })
                    l_off += 1; r_off += 1
                elif tag_sub == '- ':
                    # Check for modification pairing (next is '+' or next is '?' then '+')
                    paired = False
                    if idx + 1 < len(sub_diff):
                        if sub_diff[idx+1].startswith('+ '):
                            rows.append({
                                "left_no": i1 + l_off + 1, "left_text": content,
                                "right_no": j1 + r_off + 1, "right_text": sub_diff[idx+1][2:],
                                "type": "modified"
                            })
                            l_off += 1; r_off += 1
                            idx += 1 # Skip the '+'
                            paired = True
                        elif sub_diff[idx+1].startswith('? ') and idx + 2 < len(sub_diff) and sub_diff[idx+2].startswith('+ '):
                            rows.append({
                                "left_no": i1 + l_off + 1, "left_text": content,
                                "right_no": j1 + r_off + 1, "right_text": sub_diff[idx+2][2:],
                                "type": "modified"
                            })
                            l_off += 1; r_off += 1
                            idx += 2 # Skip '?' and '+'
                            paired = True
                    
                    if not paired:
                        rows.append({
                            "left_no": i1 + l_off + 1, "left_text": content,
                            "right_no": "", "right_text": "",
                            "type": "removed"
                        })
                        l_off += 1
                elif tag_sub == '+ ':
                    rows.append({
                        "left_no": "", "left_text": "",
                        "right_no": j1 + r_off + 1, "right_text": content,
                        "type": "added"
                    })
                    r_off += 1
                # Skip '?' lines that aren't part of a pair handled above
                idx += 1
                
        elif tag == 'delete':
            for i in range(i1, i2):
                rows.append({
                    "left_no": i + 1, "left_text": lines1[i],
                    "right_no": "", "right_text": "", "type": "removed"
                })
        elif tag == 'insert':
            for j in range(j1, j2):
                rows.append({
                    "left_no": "", "left_text": "",
                    "right_no": j + 1, "right_text": lines2[j], "type": "added"
                })
    return rows

REPORT_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Side-by-Side Content Comparison</title>
    <style>
        :root {
            --primary: #4F7CFF;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --bg: #0B0E14;
            --card: #151A23;
            --text: #F8FAFC;
        }
        body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 1.5rem; }
        .container { max-width: 1400px; margin: 0 auto; }
        .header { background: var(--card); padding: 1.5rem; border-radius: 0.75rem; box-shadow: 0 1px 3px rgba(0,0,0,0.5); margin-bottom: 1.5rem; border: 1px solid #1e293b; }
        .header h1 { margin: 0 0 0.5rem 0; font-size: 1.5rem; color: var(--text); }
        .urls { display: flex; gap: 2rem; font-size: 0.85rem; color: #94A3B8; }
        
        .diff-container { background: var(--card); border-radius: 0.75rem; box-shadow: 0 1px 3px rgba(0,0,0,0.5); overflow: hidden; border: 1px solid #1e293b; }
        .diff-table { width: 100%; border-collapse: collapse; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 13px; table-layout: fixed; }
        
        .diff-table th { background: rgba(255, 255, 255, 0.03); padding: 0.75rem; text-align: left; border-bottom: 1px solid #1e293b; color: #94a3b8; font-size: 0.75rem; text-transform: uppercase; }
        .line-no { width: 40px; text-align: right; color: #64748b; padding-right: 10px; user-select: none; background: rgba(255, 255, 255, 0.02); border-right: 1px solid #1e293b; }
        .content { padding-left: 10px; white-space: pre-wrap; word-break: break-all; vertical-align: top; padding-top: 4px; padding-bottom: 4px; }
        
        tr.equal .content { color: #94a3b8; }
        tr.added { background-color: rgba(16, 185, 129, 0.1); }
        tr.added .content { color: #34d399; }
        tr.removed { background-color: rgba(239, 68, 68, 0.1); }
        tr.removed .content { color: #f87171; }
        tr.modified { background-color: rgba(245, 158, 11, 0.1); }
        tr.modified .content { color: #fbbf24; }
        
        .type-indicator { width: 4px; padding: 0; }
        tr.added .type-indicator { background: var(--success); }
        tr.removed .type-indicator { background: var(--danger); }
        tr.modified .type-indicator { background: var(--warning); }
        
        .sticky-header { position: sticky; top: 0; z-index: 10; }
        tr.section-banner td { background: rgba(79, 124, 255, 0.12); color: #4F7CFF; font-weight: 700; font-size: 0.75rem; letter-spacing: 0.1em; text-transform: uppercase; padding: 0.5rem 1rem; border-top: 1px solid rgba(79, 124, 255, 0.3); border-bottom: 1px solid rgba(79, 124, 255, 0.3); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Content Comparison Report</h1>
            <div class="urls">
                <div><strong>STAGING:</strong> {{ staging_url }}</div>
                <div><strong>LIVE:</strong> {{ live_url }}</div>
                <div><strong>SIMILARITY:</strong> {{ summary.similarity_score | percent }}</div>
            </div>
        </div>

        <div class="diff-container">
            <table class="diff-table">
                <thead class="sticky-header">
                    <tr>
                        <th class="line-no">#</th>
                        <th>Staging Content</th>
                        <th class="line-no">#</th>
                        <th>Live Content</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in diff_rows %}
                    {% if row.left_text.startswith('──') or row.right_text.startswith('──') %}
                    <tr class="section-banner">
                        <td class="line-no"></td>
                        <td class="content" colspan="3">{{ row.left_text or row.right_text }}</td>
                    </tr>
                    {% else %}
                    <tr class="{{ row.type }}">
                        <td class="line-no">{{ row.left_no }}</td>
                        <td class="content">{{ row.left_text }}</td>
                        <td class="line-no">{{ row.right_no }}</td>
                        <td class="content">{{ row.right_text }}</td>
                    </tr>
                    {% endif %}
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

def generate_html_report(staging_url, live_url, summary, observations, output_path, live_lines, staging_lines):
    """Render the side-by-side HTML report using Jinja2."""
    env = Environment()
    env.filters['percent'] = lambda v: f"{int(v * 100)}%"
    template = env.from_string(REPORT_HTML_TEMPLATE)
    
    diff_rows = build_diff_rows(live_lines, staging_lines)
    
    html_content = template.render(
        staging_url=staging_url,
        live_url=live_url,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        summary=summary,
        observations=observations,
        diff_rows=diff_rows
    )
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

def generate_txt_report(staging_url, live_url, summary, observations, output_path):
    """Generate a simple TXT fallback report."""
    lines = [
        "URL CONTENT COMPARISON REPORT",
        "=" * 30,
        f"Staging: {staging_url}",
        f"Live:    {live_url}",
        f"Date:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "SUMMARY",
        f"- Similarity Score: {int(summary['similarity_score'] * 100)}%",
        f"- Added Lines:      {summary['counts']['added']}",
        f"- Removed Lines:    {summary['counts']['removed']}",
        f"- Modified Lines:   {summary['counts']['modified']}",
        "",
        "OBSERVATIONS",
        *[f"- {obs}" for obs in observations],
        "",
    ]
    
    if summary["added"]:
        lines.append("ADDED CONTENT (top 20)")
        lines.extend([f"+ {line}" for line in summary["added"][:20]])
        lines.append("")
        
    if summary["removed"]:
        lines.append("REMOVED CONTENT (top 20)")
        lines.extend([f"- {line}" for line in summary["removed"][:20]])
        lines.append("")
        
    if summary["modified"]:
        lines.append("MODIFIED CONTENT (top 20)")
        for change in summary["modified"][:20]:
            lines.append(f"OLD: {change['old']}")
            lines.append(f"NEW: {change['new']}")
            lines.append("-" * 10)
            
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
