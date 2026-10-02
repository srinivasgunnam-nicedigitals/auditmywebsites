import os
import sys
import json
import asyncio
import re
import random
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from playwright.async_api import async_playwright
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import tempfile

from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, File, UploadFile, BackgroundTasks
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
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
from routers.auth import require_auth, get_current_user_from_cookie
from utils.credits import check_and_deduct_credits

router = APIRouter()
# ========== AUDIT TASKS ==========

def sitemap_audit_task(url: str, session_id: str):
    """Sync wrapper for sitemap audit to handle Windows asyncio policy"""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(audit_sitemap_logic(url, session_id))


# Common headers and configuration for sitemaps
SITEMAP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

async def fetch_with_browser(target_url: str):
    """Patient browser fallback for WAF/JS challenges"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=SITEMAP_HEADERS["User-Agent"])
        pg = await ctx.new_page()
        try:
            print(f"DEBUG: [Patient Browser] Visiting {target_url}")
            await pg.goto(target_url, wait_until="commit", timeout=60000)
            
            # Initial wait to let meta-refreshes/WAF challenges initiate
            await pg.wait_for_timeout(15000)
            
            content_snap = ""
            # Robust retry for content retrieval if page is still navigating
            for i in range(5):
                try:
                    content_snap = await pg.content()
                    if "sg-captcha" in content_snap or "http-equiv=\"refresh\"" in content_snap or "Accepted" in content_snap:
                        # Found a challenge, wait 15s as requested by user
                        print(f"DEBUG: Challenge/Wait detected on {target_url}, waiting 15s for stability...")
                        await pg.wait_for_timeout(15000)
                        try:
                            await pg.wait_for_load_state("networkidle", timeout=5000)
                        except: pass
                        content_snap = await pg.content()
                    break
                except Exception as e:
                    # User requested 15s wait for staging sites
                    print(f"DEBUG: Navigation/Content error ({i+1}), waiting 15s for stabilization... ({e})")
                    await pg.wait_for_timeout(15000)
            
            if not content_snap:
                 content_snap = await pg.content()
            
            # For XML sitemaps, browser often wraps them in HTML/Pre or stylized tables.
            # The most reliable way to get RAW XML from the browser after bypassing WAF:
            try:
                raw_xml = await pg.evaluate("""async () => {
                    try {
                        const r = await fetch(location.href);
                        return await r.text();
                    } catch (e) {
                        return document.documentElement.outerHTML;
                    }
                }""")
            except:
                raw_xml = content_snap

            # Verify if it looks like XML
            if "<?xml" in raw_xml or "<urlset" in raw_xml.lower() or "<sitemapindex" in raw_xml.lower():
                final_content = raw_xml
            else:
                # Fallback to innerText if it contains XML tags
                inner_text = await pg.evaluate("() => document.body.innerText")
                if "<?xml" in inner_text:
                    final_content = inner_text
                else:
                    final_content = content_snap
            
            return 200, final_content, {"content-type": "application/xml" if "<?xml" in final_content else "text/html"}
        except Exception as e:
            print(f"DEBUG: Patient browser error for {target_url}: {e}")
            return 0, "", {}
        finally:
            await browser.close()


def _sync_fetch_with_browser(target_url: str):
    """Sync wrapper to run fetch_with_browser in a separate event loop (for Windows thread compat)."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return asyncio.run(fetch_with_browser(target_url))


async def audit_sitemap_logic(url: str, session_id: str):
    """Refactored Sitemap audit with smarter discovery and robust XML parsing"""
    db = SessionLocal()
    try:
        session = db.query(models.AuditSession).filter_by(session_id=session_id).first()
        if not session: return
        
        if not is_safe_url(url):
            session.status = "error"
            db.commit()
            return

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False, headers=SITEMAP_HEADERS) as client:
            start_time = time.time()
            errors = []
            warnings = []
            try:
                resp = await client.get(url)
                load_time_ms = int((time.time() - start_time) * 1000)
                
                if resp.status_code == 202 or (resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "").lower() and ("sg-captcha" in resp.text or "refresh" in resp.text)):
                     print(f"DEBUG: Staging/WAF suspicious response for {url}, trying browser...")
                     s, c, h = await fetch_with_browser(url)
                     if s in (200, 202):
                         # Mock a response object for the rest of the logic
                         class MockResp:
                             def __init__(self, status, content, headers):
                                 self.status_code = status
                                 self.content = content.encode('utf-8')
                                 self.text = content
                                 self.headers = headers
                         resp = MockResp(s, c, h)

                if resp.status_code not in (200, 202):
                    errors.append(f"HTTP {resp.status_code} when fetching sitemap")
                    # Do not raise Exception, continue to create result with error

                
                # Discovery Logic
                robots_status = "direct"
                robots_txt_content = ""
                final_sitemap_url = url

                # Independent robots.txt fetch (always try to capture content)
                parsed = urlparse(url)
                base_domain_url = f"{parsed.scheme}://{parsed.netloc}"
                
                # Determine "base" path from input URL (for subdirectory discovery)
                path_parts = parsed.path.strip('/').split('/')
                # If the last part has a dot, it's a file, so take the parent
                if path_parts and '.' in path_parts[-1]:
                    path_parts = path_parts[:-1]
                
                base_path = '/' + '/'.join(path_parts)
                base_path_url = f"{parsed.scheme}://{parsed.netloc}{base_path}".rstrip('/')

                try:
                    # 1. SPECIAL CASE: Staging/Subdirectory Direct Guess (High Priority)
                    # For sites like ourwebsitepreview.net/folder, go straight to sitemap.xml or sitemap_index.xml
                    if "text/html" in resp.headers.get("content-type", "").lower() or ".net" in url or "preview" in url:
                        for guess_name in ["/sitemap_index.xml", "/sitemap.xml"]:
                            direct_guess = urljoin(base_path_url + '/', guess_name.lstrip('/'))
                            print(f"DEBUG: Staging/Subdirectory detected, prioritizing direct guess: {direct_guess}")
                            s, c, h = await fetch_with_browser(direct_guess)
                            if s in (200, 202) and ("<?xml" in c or "sitemap" in c.lower()):
                                print(f"DEBUG: Found sitemap directly at {direct_guess}")
                                class MockResp:
                                    def __init__(self, status, content, headers):
                                        self.status_code = status
                                        self.content = content.encode('utf-8')
                                        self.text = content
                                        self.headers = headers
                                resp = MockResp(s, c, h)
                                final_sitemap_url = direct_guess
                                robots_status = "guessed"
                                break

                    # 2. robots.txt discovery (Always try, but prioritize subdirectory)
                    test_rob_urls = []
                    is_staging = ".net" in url or "preview" in url
                    
                    if base_path and base_path != '/':
                        test_rob_urls.append(f"{base_path_url}/robots.txt")
                    
                    if not is_staging:
                        test_rob_urls.append(f"{base_domain_url}/robots.txt")
                    
                    rob_resp = None
                    for rob_url in test_rob_urls:
                        print(f"DEBUG: Checking robots.txt at {rob_url}")
                        try:
                            temp_rob_resp = await client.get(rob_url, timeout=10)
                            
                            if temp_rob_resp.status_code == 202 or (temp_rob_resp.status_code == 200 and "text/html" in temp_rob_resp.headers.get("content-type", "").lower() and ("sg-captcha" in temp_rob_resp.text or "refresh" in temp_rob_resp.text)):
                                s, c, h = await fetch_with_browser(rob_url)
                                if s in (200, 202):
                                     class MockResp:
                                         def __init__(self, status, content, headers):
                                             self.status_code = status
                                             self.content = content.encode('utf-8')
                                             self.text = content
                                             self.headers = headers
                                     temp_rob_resp = MockResp(s, c, h)
                            
                            if temp_rob_resp.status_code in (200, 202) and ("User-agent" in temp_rob_resp.text or "Sitemap:" in temp_rob_resp.text):
                                 print(f"DEBUG: Found valid robots.txt at {rob_url}")
                                 rob_resp = temp_rob_resp
                                 break
                        except:
                            continue

                    if rob_resp and rob_resp.status_code in (200, 202):
                        robots_txt_content = rob_resp.text
                        sm_match = re.search(r'Sitemap:\s*([^\s]+)', rob_resp.text, re.I)
                        if sm_match:
                            discovered_url = sm_match.group(1).strip()
                            # If we are currently on an HTML page, try using this discovered URL
                            if "text/html" in resp.headers.get("content-type", "").lower():
                                final_sitemap_url = discovered_url
                                resp = await client.get(final_sitemap_url)
                                
                                if resp.status_code == 202 or (resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "").lower() and ("sg-captcha" in resp.text or "refresh" in resp.text)):
                                    s, c, h = await fetch_with_browser(final_sitemap_url)
                                    if s in (200, 202):
                                        class MockResp:
                                            def __init__(self, status, content, headers):
                                                self.status_code = status
                                                self.content = content.encode('utf-8')
                                                self.text = content
                                                self.headers = headers
                                        resp = MockResp(s, c, h)

                                if resp.status_code in (200, 202):
                                    robots_status = "discovered"
                                else:
                                    warnings.append(f"Discovered sitemap {final_sitemap_url} returned HTTP {resp.status_code}")
                        else:
                            if "text/html" in resp.headers.get("content-type", "").lower():
                                warnings.append("No Sitemap declaration found in robots.txt")
                    elif rob_resp and rob_resp.status_code not in (200, 202):
                        if "text/html" in resp.headers.get("content-type", "").lower():
                             warnings.append(f"robots.txt returned HTTP {rob_resp.status_code}")
                except Exception as e:
                    warnings.append(f"Failed to fetch robots.txt: {str(e)}")
                
                # Discovery Logic (Guessed)
                if robots_status == "direct" and "text/html" in resp.headers.get("content-type", "").lower():
                        # Try both domain root AND input path root
                        # Try subdirectory AND domain root variants
                        guess_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap/", "/wp-sitemap.xml"]
                        potential_urls = []
                        
                        # 1. Subdirectory specific guesses (High priority)
                        for p in guess_paths:
                            potential_urls.append(urljoin(base_path_url + '/', p.lstrip('/')))
                        
                        # 2. Domain root variants
                        for p in guess_paths:
                            u = urljoin(base_domain_url + '/', p.lstrip('/'))
                            if u not in potential_urls:
                                potential_urls.append(u)

                        for test_url in potential_urls:
                            try:
                                print(f"DEBUG: Checking guessed sitemap {test_url}")
                                test_resp = await client.get(test_url, timeout=10)
                                
                                # Browser fallback for guessed sitemaps
                                if test_resp.status_code == 202 or (test_resp.status_code == 200 and "text/html" in test_resp.headers.get("content-type", "").lower() and ("sg-captcha" in test_resp.text or "refresh" in test_resp.text)):
                                    s, c, h = await fetch_with_browser(test_url)
                                    if s in (200, 202):
                                        class MockResp:
                                            def __init__(self, status, content, headers):
                                                self.status_code = status
                                                self.content = content.encode('utf-8')
                                                self.text = content
                                                self.headers = headers
                                        test_resp = MockResp(s, c, h)

                                if test_resp and test_resp.status_code in (200, 202) and ("xml" in test_resp.headers.get("content-type", "").lower() or b"<?xml" in test_resp.content[:100]):
                                    final_sitemap_url = test_url
                                    resp = test_resp
                                    robots_status = "guessed"
                                    break
                            except:
                                continue
                        
                        if robots_status == "direct":
                             errors.append("Could not discover a valid XML sitemap from the provided URL.")

                # Process XML
                content_urls = set()
                discovered_sitemaps = []
                avg_priority = 0
                is_index = False
                sitemap_hierarchy = []
                
                if not errors:
                    try:
                        # Robust XML parsing with namespace support
                        xml_content = resp.content
                        try:
                            root = ET.fromstring(xml_content)
                            ns = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                            tag = root.tag.split('}')[-1]
                        except Exception as e:
                            print(f"DEBUG: ET parsing failed ({e}), trying BeautifulSoup fallback...")
                            # Fallback: Many sitemaps (like Yoast) look like HTML in screens
                            soup = BeautifulSoup(xml_content, 'html.parser')
                            # Look for <loc> tags directly if XML tags are present in HTML (common in browser wraps)
                            locs = soup.find_all('loc')
                            if locs:
                                # Create a fake root that looks like a sitemap index if it contains .xml links
                                is_index = any('.xml' in l.text.lower() for l in locs)
                                tag = 'sitemapindex' if is_index else 'urlset'
                                # Re-wrap for uniform processing
                                fake_xml = f'<{tag}>'
                                for l in locs:
                                    item_tag = 'sitemap' if is_index else 'url'
                                    fake_xml += f'<{item_tag}><loc>{l.text.strip()}</loc></{item_tag}>'
                                fake_xml += f'</{tag}>'
                                root = ET.fromstring(fake_xml)
                                ns = {}
                                print(f"DEBUG: Successfully recovered {len(locs)} items via soup.")
                            else:
                                raise e # Re-raise if soup found nothing
                        
                        tag = root.tag.split('}')[-1]
                        is_index = (tag == 'sitemapindex')
                        
                        # Use sitemap URL as root for hierarchy
                        sitemap_hierarchy.append({
                            "url": final_sitemap_url,
                            "type": "Sitemap Index" if is_index else "Sitemap",
                            "count": 0,
                            "status": "OK",
                            "last_mod": datetime.now().strftime("%Y-%m-%d")
                        })
                        
                        priorities = []
                        
                        # Handle both sitemapindex and urlset
                        item_tag = 'sitemap' if is_index else 'url'
                        item_selector = f'.//ns:{item_tag}' if ns else f'.//{item_tag}'
                        
                        found_items = root.findall(item_selector, ns)
                        print(f"DEBUG: Found {len(found_items)} items in sitemap {final_sitemap_url}")
                        
                        for item in found_items:
                            def get_sub(p_node, s_tag):
                                return p_node.find(f'ns:{s_tag}', ns) if ns else p_node.find(s_tag)

                            loc = get_sub(item, 'loc')
                            lastmod = get_sub(item, 'lastmod')
                            last_mod_val = lastmod.text.strip() if lastmod is not None and lastmod.text else datetime.now().strftime("%Y-%m-%d")

                            if loc is not None and loc.text:
                                url_text = loc.text.strip()
                                
                                if is_index:
                                    discovered_sitemaps.append(url_text)
                                    sitemap_hierarchy.append({
                                        "url": url_text,
                                        "type": "Sitemap",
                                        "count": 0,
                                        "status": "OK", 
                                        "last_mod": last_mod_val
                                    })
                                else:
                                    content_urls.add(url_text)
                                
                                if not is_index:
                                    prio = get_sub(item, 'priority')
                                    if prio is not None and prio.text:
                                        try:
                                            p_val = float(prio.text)
                                            priorities.append(p_val)
                                        except:
                                            pass
                                            pass
                        
                        # If Index, fetch children to get counts
                        if is_index and discovered_sitemaps:
                             print(f"DEBUG: Sitemap Index with {len(discovered_sitemaps)} children. Fetching counts...", flush=True)
                             async def fetch_child_count(child_url, index):
                                 try:
                                     async with httpx.AsyncClient(timeout=15.0, verify=False, headers=SITEMAP_HEADERS) as c_client:
                                         c_resp = None
                                         try:
                                             c_resp = await c_client.get(child_url)
                                             
                                             # Browser fallback for children too
                                             if c_resp.status_code == 202 or (c_resp.status_code == 200 and "text/html" in c_resp.headers.get("content-type", "").lower() and ("sg-captcha" in c_resp.text or "refresh" in c_resp.text)):
                                                 s, c, h = await fetch_with_browser(child_url)
                                                 if s in (200, 202):
                                                     class MockResp:
                                                         def __init__(self, status, content, headers):
                                                             self.status_code = status
                                                             self.content = content.encode('utf-8')
                                                             self.text = content
                                                             self.headers = headers
                                                     c_resp = MockResp(s, c, h)
                                         except:
                                             pass
                                         
                                         if c_resp and c_resp.status_code in (200, 202):
                                             try:
                                                 c_content = c_resp.content
                                                 try:
                                                     c_root = ET.fromstring(c_content)
                                                     c_ns = {'ns': c_root.tag.split('}')[0].strip('{')} if '}' in c_root.tag else {}
                                                 except:
                                                     # BeautifulSoup recovery for children
                                                     c_soup = BeautifulSoup(c_content, 'html.parser')
                                                     c_locs = c_soup.find_all('loc')
                                                     if c_locs:
                                                         c_fake_xml = '<urlset>'
                                                         for cl in c_locs:
                                                             c_fake_xml += f'<url><loc>{cl.text.strip()}</loc></url>'
                                                         c_fake_xml += '</urlset>'
                                                         c_root = ET.fromstring(c_fake_xml)
                                                         c_ns = {}
                                                     else: raise Exception("No items")

                                                 c_selector = './/ns:url' if c_ns else './/url'
                                                 items = c_root.findall(c_selector, c_ns)
                                                 c_count = len(items)
                                                 c_urls = []
                                                 for itm in items:
                                                     l_node = itm.find('ns:loc', c_ns) if c_ns else itm.find('loc')
                                                     if l_node is not None and l_node.text:
                                                         c_urls.append(l_node.text.strip())
                                                 return index, c_count, "OK", c_urls
                                             except Exception as parse_err:
                                                 print(f"DEBUG: Child {child_url} parse error: {parse_err}")
                                                 return index, 0, "Parse Error", []
                                         else:
                                             return index, "-", f"HTTP {c_resp.status_code if c_resp else 'Fail'}", []
                                 except Exception as e:
                                     print(f"DEBUG: fetch_child_count fatal for {child_url}: {e}")
                                     return index, "-", "Error", []

                              # Limit concurrency
                             chunk_size = 5
                             for i in range(0, len(discovered_sitemaps), chunk_size):
                                 chunk = discovered_sitemaps[i:i+chunk_size]
                                 tasks = []
                                 for j, c_url in enumerate(chunk):
                                     # hierarchy index is 1 + total_processed (since 0 is root)
                                     h_idx = 1 + i + j
                                     tasks.append(fetch_child_count(c_url, h_idx))
                                 
                                 results = await asyncio.gather(*tasks)
                                 for h_idx, cnt, sts, c_urllist in results:
                                     if h_idx < len(sitemap_hierarchy):
                                         sitemap_hierarchy[h_idx]["count"] = cnt
                                         if sts != "OK": sitemap_hierarchy[h_idx]["status"] = sts
                                         for c_u in c_urllist:
                                             content_urls.add(c_u)
                        
                        # Update hierarchy count (Root node)
                        # If it's an index, it should show the number of sitemaps it contains
                        # If it's a regular sitemap, it should show the total unique pages
                        sitemap_hierarchy[0]["count"] = len(discovered_sitemaps) if is_index else len(content_urls)
                        
                        # Ensure content_urls doesn't include the sitemap URLs themselves
                        content_urls -= set(discovered_sitemaps)
                        # Also remove the root sitemap itself just in case
                        if final_sitemap_url in content_urls: content_urls.remove(final_sitemap_url)
                        
                        if priorities:
                            avg_val = sum(priorities) / len(priorities)
                            avg_priority = int(avg_val * 100)
                        else:
                            avg_priority = 50 if content_urls else 0
                            
                    except ET.ParseError as e:
                         errors.append(f"Invalid XML format: {str(e)}")
                    except Exception as e:
                         errors.append(f"Error parsing sitemap: {str(e)[:100]}")

                count = len(content_urls)
                found_urls = list(content_urls) # For legacy compatibility in the rest of the function
                
                # --- Link Analysis & Reachability ---
                reachability_results = {}
                link_details = []
                internal_links_stats = {
                    "total": 0,
                    "internal": 0,
                    "external": 0,
                    "all_internal_links": [],
                    "external_domains": {},
                    "seo_insights": {
                        "missing_alt_count": 0,
                        "duplicate_anchors": [],
                        "category_distribution": {"navigation": 0, "content": 0, "cta": 0, "footer": 0}
                    }
                }
                
                if found_urls and not errors:
                    # Crawl Logic: Limit to 20 pages for deep analysis to keep it fast
                    crawling_candidates = found_urls
                    # (Removed redundant is_index child extraction since content_urls now has all pages)

                    sample_size = min(20, len(crawling_candidates))
                    sample_urls = random.sample(crawling_candidates, sample_size)
                    print(f"DEBUG: Sitemap Auditor - Starting crawl of {len(sample_urls)} pages...", flush=True)
                    
                    parsed_base = urlparse(url)
                    base_domain = parsed_base.netloc
                    
                    async def process_url(target_url):
                        print(f"DEBUG: Crawling {target_url}", flush=True)
                        page_links = []
                        status_code = 0
                        try:
                            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=False) as check_client:
                                try:
                                    # Fetch page content with retry
                                    page_resp = None
                                    for retry in range(2):
                                        try:
                                            page_resp = await check_client.get(target_url)
                                            break
                                        except:
                                            if retry == 1: raise
                                            await asyncio.sleep(1)

                                    if page_resp:
                                        status_code = page_resp.status_code
                                    else:
                                        status_code = 0
                                    
                                    if status_code == 200 and "text/html" in page_resp.headers.get("content-type", "").lower():
                                        soup = BeautifulSoup(page_resp.text, 'html.parser')
                                        
                                        # Extract Links
                                        anchors = soup.find_all('a', href=True)
                                        for a in anchors:
                                            href = a['href'].strip()
                                            if not href or href.startswith(('javascript:', 'mailto:', 'tel:')):
                                                continue
                                                
                                            full_url = urljoin(target_url, href)
                                            parsed_link = urlparse(full_url)
                                            
                                            # Anchor Text/Type
                                            anchor_text = a.get_text(strip=True)
                                            anchor_type = "text"
                                            has_img = a.find('img')
                                            
                                            if has_img:
                                                if anchor_text: anchor_type = "mixed"
                                                else: 
                                                    anchor_type = "image"
                                                    alt_text = has_img.get('alt', '').strip()
                                                    if alt_text: anchor_text = f"IMG: {alt_text}"
                                                    else: anchor_text = "IMG: [No Alt Text]"
                                            
                                            if not anchor_text: anchor_text = "[Empty]"
                                            
                                            # Internal/External
                                            link_type = "external"
                                            if parsed_link.netloc == base_domain or not parsed_link.netloc:
                                                link_type = "internal"
                                            
                                            # Category (Heuristic)
                                            category = "content"
                                            # Check parents for nav/footer
                                            parents = [p.name for p in a.parents] # gets tag names
                                            classes = str(a.get('class', [])) + str(a.parent.get('class', []))
                                            
                                            if 'nav' in parents or 'header' in parents or 'nav' in classes.lower():
                                                category = "navigation"
                                            elif 'footer' in parents or 'footer' in classes.lower():
                                                category = "footer"
                                            elif 'btn' in classes.lower() or 'button' in classes.lower() or 'cta' in classes.lower():
                                                category = "cta"
                                            
                                            page_links.append({
                                                "source_url": target_url,
                                                "target_url": full_url,
                                                "anchor_text": anchor_text,
                                                "anchor_type": anchor_type,
                                                "link_type": link_type,
                                                "category": category,
                                                "has_alt": bool(has_img.get('alt')) if has_img else True
                                            })
                                            
                                except Exception as e:
                                    pass
                                    
                                return target_url, status_code, page_links
                        except:
                            return target_url, 0, []

                    check_tasks = [process_url(u) for u in sample_urls]
                    audit_results = await asyncio.gather(*check_tasks)
                    
                    # Aggregate Results
                    all_found_links = []
                    
                    for t_url, t_code, t_links in audit_results:
                        reachability_results[t_url] = t_code
                        if t_code >= 400:
                            warnings.append(f"URL {t_url} returned status {t_code}")
                        elif t_code == 0:
                            warnings.append(f"Could not reach {t_url}")
                            
                        all_found_links.extend(t_links)
                        
                    # Process Aggregated Stats
                    seen_anchors = {} # url -> set(anchors)
                    
                    for link in all_found_links:
                        internal_links_stats["total"] += 1
                        
                        if link["link_type"] == "internal":
                            internal_links_stats["internal"] += 1
                            if link["target_url"] not in internal_links_stats["all_internal_links"]:
                                internal_links_stats["all_internal_links"].append(link["target_url"])
                        else:
                            internal_links_stats["external"] += 1
                            dom = urlparse(link["target_url"]).netloc
                            internal_links_stats["external_domains"][dom] = internal_links_stats["external_domains"].get(dom, 0) + 1
                            
                        # SEO Insights
                        if not link["has_alt"]:
                            internal_links_stats["seo_insights"]["missing_alt_count"] += 1
                        
                        # Duplicate Anchors (Same text, different URL? Or Same URL diff text?)
                        # Definition: "Same text pointing to different URLs"
                        txt_key = link["anchor_text"].lower()
                        if txt_key not in seen_anchors:
                            seen_anchors[txt_key] = set()
                        seen_anchors[txt_key].add(link["target_url"])
                        
                        # Category
                        cat = link["category"]
                        if cat in internal_links_stats["seo_insights"]["category_distribution"]:
                             internal_links_stats["seo_insights"]["category_distribution"][cat] += 1
                             
                    # Finalize Duplicates
                    for txt, urls in seen_anchors.items():
                        if len(urls) > 1:
                            internal_links_stats["seo_insights"]["duplicate_anchors"].append(txt)
                            
                    link_details = all_found_links

                # Score Calculation (Enhanced)
                score = 0
                if not errors:
                    score = 100
                    # ... (Existing scoring logic + link health)
                    if warnings: score -= (len(warnings) * 5)
                    
                    if reachability_results:
                        failures = sum(1 for s in reachability_results.values() if s >= 400 or s == 0)
                        failure_rate = failures / len(reachability_results)
                        score -= int(failure_rate * 40)
                    
                    # Deduct for missing alt text (capped)
                    if internal_links_stats["seo_insights"]["missing_alt_count"] > 0:
                        score -= min(10, internal_links_stats["seo_insights"]["missing_alt_count"])

                    if robots_status == "error": score -= 10
                    elif robots_status == "direct" and count == 0: score -= 20
                    
                    score = max(0, min(100, score))
                else:
                    score = 0
                
                result = models.SitemapResult(
                    session_id=session_id,
                    url=final_sitemap_url,
                    is_index=is_index,
                    url_count=count,
                    child_sitemaps=json.dumps(found_urls if is_index else []),
                    avg_priority=avg_priority,
                    robots_status=robots_status,
                    load_time_ms=load_time_ms,
                    reachability_sample=json.dumps(reachability_results),
                    errors=json.dumps(errors),
                    warnings=json.dumps(warnings),
                    score=score,
                    # New Fields
                    sitemap_urls=json.dumps(found_urls),
                    internal_links=json.dumps(internal_links_stats),
                    link_details=json.dumps(link_details),
                    sitemap_hierarchy=json.dumps(sitemap_hierarchy),
                    robots_txt_content=robots_txt_content
                )
                db.add(result)
                
                db.expire_all()
                if session:
                    db.refresh(session)
                    if session.status != "stopped":
                        session.status = "completed"
                        session.completed = 1
                        session.completed_at = datetime.utcnow()
                        db.commit()
            except Exception as e:
                print(f"Sitemap Internal Error: {e}")
                if session:
                    session.status = "error"
                    db.commit()
    except Exception as e:
        print(f"Sitemap Audit Fatal: {e}")
        if session:
            db.refresh(session)
            session.status = "error"
            db.commit()
    finally:
        db.close()

# ========== ROUTES ==========

@router.get("/platform/sitemap", response_class=HTMLResponse)
async def sitemap_audit_page(request: Request, user = Depends(require_auth)):
    return templates.TemplateResponse("sitemaps.html", {"request": request, "user": user})

@router.get("/scan/xml-sitemaps")
async def sitemap_scan_redirect(request: Request, user = Depends(require_auth)):
    """Backward compatibility for xml-sitemaps scan page"""
    return await sitemap_audit_page(request, user)

@router.get("/scan/sitemap-history")
async def sitemap_history_redirect(request: Request, db: Session = Depends(get_db)):
    """Redirect old sitemap history to unified history"""
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
    return RedirectResponse("/platform/history?type=sitemap")

@router.post("/upload/sitemap")
async def upload_sitemap(
    request: Request,
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    session_name: str = Form("Sitemap Scan"),
    db: Session = Depends(get_db)
):
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401, detail="Not authenticated")

    # Credit deduction (1 credit for the sitemap URL)
    try:
        _, low_credit_warning = check_and_deduct_credits(user.id, 1, db)
    except HTTPException as e:
        return JSONResponse({"error": e.detail}, status_code=e.status_code)

    request.state.credits_used = 1

    session_id = f"sm_{uuid.uuid4().hex[:8]}"
    
    new_session = models.AuditSession(
        session_id=session_id,
        user_id=user.id,
        session_type="sitemap",
        name=session_name,
        urls=json.dumps([url]),
        credits_balance=user.credits,
        browsers=json.dumps(["Engine"]),
        resolutions=json.dumps(["Default"]),
        credits_used=1,
        total_expected=1,
        status="running",
        completed=0
    )
    db.add(new_session)
    db.commit()
    
    background_tasks.add_task(sitemap_audit_task, url, session_id)
    running_tasks[session_id] = "sitemap"
    
    return JSONResponse({"session": session_id, "total_expected": 1, "type": "sitemap", "low_credits": low_credit_warning})

@router.get("/sitemap-results/{session_id}")
async def sitemap_results_view(session_id: str, request: Request, db: Session = Depends(get_db)):
    user = await get_current_user_from_cookie(request, db)
    if not user: return RedirectResponse("/login")
        
    session = db.query(models.AuditSession).filter(models.AuditSession.session_id == session_id, models.AuditSession.user_id == user.id).first()
    if not session: raise HTTPException(status_code=404, detail="Session not found")
    
    if session.status == "running" or "crawling" in session.status.lower():
        return RedirectResponse(url="/platform/dashboard?msg=Audit%20in%20progress", status_code=303)
    
    results = db.query(models.SitemapResult).filter_by(session_id=session_id).all()
    
    return templates.TemplateResponse("sitemap_report.html", {
        "request": request, "user": user, "session": session, "session_id": session_id, "results": results
    })

@router.get("/api/results/sitemap/{session_id}")
async def get_sitemap_results(session_id: str, request: Request, db: Session = Depends(get_db)):
    """API endpoint to get sitemap audit results as JSON"""
    user = await get_current_user_from_cookie(request, db)
    if not user: raise HTTPException(status_code=401)
    
    r = db.query(models.SitemapResult).filter_by(session_id=session_id).first()
    if not r: return {"results": {}}
    
    return {"results": {
        "url": r.url,
        "is_index": r.is_index,
        "url_count": r.url_count,
        "child_sitemaps": json.loads(r.child_sitemaps) if r.child_sitemaps else [],
        "robots_status": r.robots_status,
        "load_time_ms": r.load_time_ms,
        "score": r.score,
        "issues": json.loads(r.issues) if r.issues else [],
        "sitemap_urls": json.loads(r.sitemap_urls) if r.sitemap_urls else [],
        "sitemap_hierarchy": json.loads(r.sitemap_hierarchy) if r.sitemap_hierarchy else [],
        "robots_txt_content": r.robots_txt_content,
        "link_details": json.loads(r.link_details) if r.link_details else [],
        "internal_links": json.loads(r.internal_links) if r.internal_links else {}
    }}

@router.get("/results/sitemap/{session_id}")
async def results_sitemap_redirect(session_id: str, request: Request, db: Session = Depends(get_db)):
    """Redirect old URL pattern to new one"""
    return await sitemap_results_view(session_id, request, db)
@router.get("/api/sitemap/inspect")
async def inspect_sitemap_content(url: str, user = Depends(require_auth)):
    """Fetch sitemap content and return parsed entries"""
    if not url or not is_safe_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
        
    async with httpx.AsyncClient(verify=False, follow_redirects=True, headers=SITEMAP_HEADERS) as client:
        try:
            resp = await client.get(url, timeout=15)
            content = resp.content
            
            # Use browser if challenge detected (202 or HTML challenge)
            if resp.status_code == 202 or (resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "").lower() and ("sg-captcha" in resp.text or "refresh" in resp.text)):
                print(f"DEBUG: Inspector detected challenge for {url}, trying browser...")
                from fastapi.concurrency import run_in_threadpool
                s, c, h = await run_in_threadpool(_sync_fetch_with_browser, url)
                if s in (200, 202):
                    content = c.encode('utf-8')
                else:
                    raise HTTPException(status_code=403, detail=f"Failed to bypass security challenges for this sitemap. Status: {s}")

            if not content:
                raise HTTPException(status_code=404, detail="Sitemap content is empty")

            # Robust parsing with BeautifulSoup fallback
            try:
                try:
                    root = ET.fromstring(content)
                    ns = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                    tag = root.tag.split('}')[-1]
                except Exception as e:
                    print(f"DEBUG: Inspector ET parse failed, trying soup fallback: {e}")
                    soup = BeautifulSoup(content, 'html.parser')
                    locs = soup.find_all('loc')
                    if locs:
                        is_idx = any('.xml' in l.text.lower() for l in locs)
                        tag = 'sitemapindex' if is_idx else 'urlset'
                        fake_xml = f'<{tag}>'
                        for l in locs:
                            item_t = 'sitemap' if is_idx else 'url'
                            fake_xml += f'<{item_t}><loc>{l.text.strip()}</loc></{item_t}>'
                        fake_xml += f'</{tag}>'
                        root = ET.fromstring(fake_xml)
                        ns = {}
                    else: 
                        raise Exception("No <loc> tags discovered in content")

                entries = []
                is_index = (tag == 'sitemapindex')
                item_tag = 'sitemap' if is_index else 'url'
                item_selector = f'.//ns:{item_tag}' if ns else f'.//{item_tag}'
                
                found_items = root.findall(item_selector, ns)
                for item in found_items:
                    loc = item.find('ns:loc', ns) if ns else item.find('loc')
                    lastmod = item.find('ns:lastmod', ns) if ns else item.find('lastmod')
                    if loc is not None and loc.text:
                        entries.append({
                            "loc": loc.text.strip(),
                            "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else "-"
                        })
                
                return JSONResponse({"entries": entries})
                
            except Exception as e:
                print(f"DEBUG: Inspector parse error: {e}")
                raise HTTPException(status_code=422, detail=f"Parse Error: {str(e)}")

        except HTTPException as he:
            raise he
        except Exception as e:
            print(f"DEBUG: Inspector fetch error: {e}")
            raise HTTPException(status_code=500, detail=f"Fetch Error: {str(e)}")
