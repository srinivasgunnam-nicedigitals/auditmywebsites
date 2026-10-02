import httpx
import asyncio
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import time
from collections import deque

# Simulated fixed logic
def fix_url(url):
    if not url.startswith(('http://', 'https://')):
        return 'https://' + url
    return url

async def test_fixed_logic(start_url):
    print(f"\n--- Testing Fixed Logic for: {start_url} ---")
    start_url = fix_url(start_url)
    print(f"Fixed URL: {start_url}")
    
    visited = set()
    to_crawl = deque([start_url])
    discovered = {start_url}
    
    parsed_start = urlparse(start_url)
    base_netloc = parsed_start.netloc.lower().replace("www.", "")
    print(f"Base Netloc: '{base_netloc}'")
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}
    
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False, headers=headers) as client:
        while to_crawl and len(visited) < 5:
            url = to_crawl.popleft()
            if url in visited: continue
            visited.add(url)
            print(f"Fetching: {url}")
            
            try:
                resp = await client.get(url)
                print(f"  Status: {resp.status_code}")
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    links_found = 0
                    for a in soup.find_all('a', href=True):
                        href = a['href'].split('#')[0].rstrip('/')
                        if not href or href.startswith(('javascript:', 'mailto:', 'tel:', 'data:', 'ftp:')): continue
                        
                        full_url = urljoin(url, href)
                        parsed = urlparse(full_url)
                        link_netloc = parsed.netloc.lower().replace("www.", "")
                        
                        if link_netloc == base_netloc:
                            links_found += 1
                            if full_url not in discovered:
                                discovered.add(full_url)
                                to_crawl.append(full_url)
                    print(f"  Links found: {links_found}")
            except Exception as e:
                print(f"  Error: {e}")

    print(f"Discovered {len(discovered)} total URLs")
    return len(discovered)

async def main():
    success = True
    # Test 1: capital W, no scheme
    count = await test_fixed_logic("Www.alulex.co.za")
    if count <= 1: success = False
    
    # Test 2: no www, no scheme
    count = await test_fixed_logic("alulex.co.za")
    if count <= 1: success = False
    
    print(f"\nOverall Success: {success}")

if __name__ == "__main__":
    asyncio.run(main())
