import asyncio
import os
import sys
from collections import deque
from urllib.parse import urlparse, urljoin
import httpx

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

SKIP_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css', '.js',
             '.zip', '.xml', '.json', '.svg', '.ico', '.mp4', '.webp',
             '.woff', '.woff2', '.mp3', '.wav', '.avi'}

async def test_sitemap(start_url):
    if not start_url.startswith(('http://', 'https://')):
        start_url = 'https://' + start_url
    start_url = start_url.rstrip('/')
    
    parsed_start = urlparse(start_url)
    base_netloc = parsed_start.netloc.lower().replace("www.", "")
    
    discovered = {start_url}
    to_crawl = deque([start_url])
    
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=False, headers=headers) as client:
        sitemap_urls = [
            urljoin(start_url + '/', 'sitemap.xml'),
            urljoin(start_url + '/', 'sitemap_index.xml')
        ]
        
        async def fetch_sitemap_links(s_url):
            try:
                resp = await client.get(s_url)
                if resp.status_code == 200 and ('xml' in resp.headers.get('content-type', '').lower() or 'xml' in resp.text[:200].lower()):
                    import re
                    locs = re.findall(r'<loc[^>]*>(.*?)</loc>', resp.text, re.IGNORECASE)
                    found = set()
                    for loc in locs:
                        loc = loc.strip()
                        if loc.startswith(('http://', 'https://')):
                            parsed_loc = urlparse(loc)
                            if parsed_loc.netloc.lower().replace("www.", "") == base_netloc:
                                if not any(loc.lower().endswith(ext) for ext in SKIP_EXTS):
                                    found.add(loc)
                    
                    sub_sitemaps = [l for l in found if l.lower().endswith('.xml')]
                    actual_pages = found - set(sub_sitemaps)
                    
                    print(f"Found {len(sub_sitemaps)} sub-sitemaps and {len(actual_pages)} direct pages in {s_url}")
                    
                    if sub_sitemaps:
                        for sub_url in sub_sitemaps[:10]:
                            try:
                                sub_resp = await client.get(sub_url)
                                if sub_resp.status_code == 200:
                                    sub_locs = re.findall(r'<loc[^>]*>(.*?)</loc>', sub_resp.text, re.IGNORECASE)
                                    for sub_loc in sub_locs:
                                        sub_loc = sub_loc.strip()
                                        if sub_loc.startswith(('http://', 'https://')):
                                            p_loc = urlparse(sub_loc)
                                            if p_loc.netloc.lower().replace("www.", "") == base_netloc:
                                                if not any(sub_loc.lower().endswith(ext) for ext in SKIP_EXTS):
                                                    actual_pages.add(sub_loc)
                            except: pass
                    
                    print(f"Total pages extracted from sitemaps under {s_url}: {len(actual_pages)}")
                    for ap in actual_pages:
                        if ap not in discovered:
                            discovered.add(ap)
                            to_crawl.append(ap)
            except Exception as e:
                print(f"Failed {s_url}: {e}")

        await asyncio.gather(*[fetch_sitemap_links(su) for su in sitemap_urls])
        return list(discovered)

async def main():
    urls = await test_sitemap('https://www.nicedigitals.com')
    print('Total sitemap injected found:', len(urls))

asyncio.run(main())
