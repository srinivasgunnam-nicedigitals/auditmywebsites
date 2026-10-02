import httpx
import uuid
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import asyncio
import time
from collections import deque
from playwright.async_api import async_playwright

async def fetch_sitemap_urls(start_url: str) -> set[str]:
    """Helper to fetch URLs from sitemap as a seed for single-pass crawling."""
    sitemap_urls_found = set()
    if start_url and not start_url.startswith(('http://', 'https://')):
        start_url = 'https://' + start_url
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/xml,application/xml,application/xhtml+xml,text/html;q=0.9,text/plain;q=0.8,image/png,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.5",
    }
        
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False, headers=headers) as client:
        try:
            sitemap_paths = ["sitemap.xml", "sitemap_index.xml", "sitemap"]
            for sp in sitemap_paths:
                s_url = f"{start_url.rstrip('/')}/{sp}"
                try:
                    s_resp = await client.get(s_url, timeout=5.0)
                    if s_resp.status_code == 200:
                        from xml.etree import ElementTree as ET
                        try:
                            root = ET.fromstring(s_resp.content)
                            namespaces = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                            for loc in root.findall('.//ns:loc', namespaces) if namespaces else root.findall('.//loc'):
                                loc_url = loc.text.strip()
                                if loc_url.endswith('.xml'):
                                    try:
                                        c_resp = await client.get(loc_url, timeout=5.0)
                                        if c_resp.status_code == 200:
                                            c_root = ET.fromstring(c_resp.content)
                                            c_ns = {'ns': c_root.tag.split('}')[0].strip('{')} if '}' in c_root.tag else {}
                                            for cloc in c_root.findall('.//ns:loc', c_ns) if c_ns else c_root.findall('.//loc'):
                                                sitemap_urls_found.add(cloc.text.strip().rstrip('/'))
                                    except: pass
                                else:
                                    sitemap_urls_found.add(loc_url.rstrip('/'))
                        except Exception as e:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
    return sitemap_urls_found

async def discover_urls(start_url: str, max_pages: int = 999999, max_time: int = 86400, progress_callback=None):
    """
    Crawls the start_url to find ALL internal links using BFS with Playwright.
    Returns a list of unique discovered URLs.
    Includes a progress callback for UI updates.
    """
    print(f"DEBUG: Starting discover_urls for {start_url}")
    visited = set()
    to_crawl = deque([start_url])
    discovered = {start_url}
    
    parsed_start = urlparse(start_url)
    base_domain = parsed_start.netloc.lower().replace("www.", "")
    
    if not base_domain:
        return [start_url]
        
    start_time = time.monotonic()
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            
            # --- Sitemap Discovery Fallback (using httpx for speed) ---
            sitemap_urls_found = set()
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False) as client:
                try:
                    sitemap_paths = ["sitemap.xml", "sitemap_index.xml"]
                    for sp in sitemap_paths:
                        s_url = f"{start_url.rstrip('/')}/{sp}"
                        print(f"DEBUG: Checking sitemap {s_url}")
                        s_resp = await client.get(s_url, timeout=5.0)
                        if s_resp.status_code == 200:
                            print(f"DEBUG: Found sitemap at {s_url}")
                            from xml.etree import ElementTree as ET
                            try:
                                root = ET.fromstring(s_resp.content)
                                namespaces = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                                for loc in root.findall('.//ns:loc', namespaces) if namespaces else root.findall('.//loc'):
                                    loc_url = loc.text.strip()
                                    if loc_url.endswith('.xml'):
                                        try:
                                            print(f"DEBUG: Checking sub-sitemap {loc_url}")
                                            c_resp = await client.get(loc_url, timeout=5.0)
                                            if c_resp.status_code == 200:
                                                c_root = ET.fromstring(c_resp.content)
                                                c_ns = {'ns': c_root.tag.split('}')[0].strip('{')} if '}' in c_root.tag else {}
                                                for cloc in c_root.findall('.//ns:loc', c_ns) if c_ns else c_root.findall('.//loc'):
                                                    sitemap_urls_found.add(cloc.text.strip())
                                        except: pass
                                    else:
                                        sitemap_urls_found.add(loc_url)
                            except Exception as e:
                                print(f"DEBUG: Sitemap parse error: {e}")
                except Exception as e:
                    print(f"DEBUG: Sitemap fetch error: {e}")

            if sitemap_urls_found:
                print(f"DEBUG: Sitemap discovery found {len(sitemap_urls_found)} total URLs")
                for s_url in sitemap_urls_found:
                    norm_s_url = s_url.rstrip('/')
                    if base_domain in s_url.lower():
                        if norm_s_url not in {d.rstrip('/') for d in discovered}:
                            discovered.add(s_url)
                            if progress_callback:
                                try: await progress_callback(1)
                                except: pass
                to_crawl.extend([u for u in sitemap_urls_found if u not in visited])

            # BFS with Playwright
            semaphore = asyncio.Semaphore(3) # Limit concurrency for local resources

            async def fetch_page(url):
                if url in visited: return []
                visited.add(url)
                
                async with semaphore:
                    page = None
                    try:
                        page = await context.new_page()
                        # Use domcontentloaded instead of networkidle (faster & more reliable)
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        
                        # Challenge detection for staging URLs
                        is_staging = any(x in url.lower() for x in ["staging", "stagging", "preview", "ourwebsitepreview"])
                        if is_staging and response and (response.status == 202 or "sg-captcha" in response.headers):
                            print(f"  [challenge] Staging URL challenge on {url}, waiting 15s...", flush=True)
                            await page.wait_for_timeout(15000)
                        
                        # Extra time for dynamic links or JS renders
                        await page.wait_for_timeout(1500)
                        
                        links = await page.eval_on_selector_all(
                            "a[href]",
                            "els => els.map(e => e.href)"
                        )
                        print(f"DEBUG: Found {len(links)} raw links on {url}")
                        
                        new_links = []
                        for full_url in links:
                            full_url = full_url.split('#')[0].strip()
                            if not full_url or full_url.startswith(('javascript:', 'mailto:', 'tel:', 'data:', 'ftp:')): continue
                            
                            norm_url = full_url.rstrip('/')
                            parsed = urlparse(full_url)
                            
                            if base_domain in parsed.netloc.lower() and parsed.scheme in ('http', 'https'):
                                if not any(full_url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css', '.js', '.zip', '.xml', '.json', '.svg', '.ico', '.mp4', '.webp']):
                                    if norm_url not in {d.rstrip('/') for d in discovered}:
                                        discovered.add(full_url)
                                        if progress_callback:
                                            try: await progress_callback(1)
                                            except: pass
                                        new_links.append(full_url)
                        return new_links
                    except Exception as e:
                        print(f"Error crawling {url}: {e}")
                        return []
                    finally:
                        if page:
                            try:
                                await page.close()
                            except:
                                pass

            while to_crawl and len(visited) < max_pages:
                if time.monotonic() - start_time > max_time:
                    break
                    
                batch = []
                while to_crawl and len(batch) < 5 and (len(visited) + len(batch)) < max_pages:
                    url = to_crawl.popleft()
                    if url not in visited:
                        batch.append(url)
                
                if not batch: break
                
                tasks = [fetch_page(url) for url in batch]
                results = await asyncio.gather(*tasks)
                for res in results:
                    to_crawl.extend(res)

            await browser.close()
            print(f"DEBUG: Discovery finished. Found {len(discovered)} total URLs.")
    except Exception as e:
        import traceback
        print(f"Crawler fatal error: {e}")
        traceback.print_exc()
    finally:
        # Ensure browser is closed even on error
        try:
            if 'browser' in locals():
                await browser.close()
        except:
            pass
        
    return list(discovered)
