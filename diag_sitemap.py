import httpx
import asyncio
from xml.etree import ElementTree as ET

async def fetch_sitemap_urls_debug(start_url: str) -> set[str]:
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
                print(f"Checking {s_url}...")
                try:
                    s_resp = await client.get(s_url, timeout=5.0)
                    print(f"  Status: {s_resp.status_code}")
                    if s_resp.status_code == 200:
                        try:
                            root = ET.fromstring(s_resp.content)
                            namespaces = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                            locs = root.findall('.//ns:loc', namespaces) if namespaces else root.findall('.//loc')
                            print(f"  Found {len(locs)} loc elements in {s_url}")
                            for loc in locs:
                                loc_url = loc.text.strip()
                                if loc_url.endswith('.xml'):
                                    print(f"    Sub-sitemap detected: {loc_url}")
                                    try:
                                        c_resp = await client.get(loc_url, timeout=5.0)
                                        if c_resp.status_code == 200:
                                            c_root = ET.fromstring(c_resp.content)
                                            c_ns = {'ns': c_root.tag.split('}')[0].strip('{')} if '}' in c_root.tag else {}
                                            clocs = c_root.findall('.//ns:loc', c_ns) if c_ns else c_root.findall('.//loc')
                                            print(f"      Found {len(clocs)} URLs in sub-sitemap")
                                            for cloc in clocs:
                                                sitemap_urls_found.add(cloc.text.strip())
                                    except Exception as e:
                                        print(f"      Error fetching sub-sitemap: {e}")
                                else:
                                    sitemap_urls_found.add(loc_url)
                        except Exception as e:
                            print(f"  Sitemap parse error: {e}")
                except Exception as e:
                    print(f"  Request error: {e}")
        except Exception as e:
            print(f"Fatal error: {e}")
    return sitemap_urls_found

async def main():
    urls = await fetch_sitemap_urls_debug("https://alulex.co.za")
    print(f"\nTotal unique URLs found across all sitemaps: {len(urls)}")
    for u in sorted(list(urls)):
        print(f"  {u}")

if __name__ == "__main__":
    asyncio.run(main())
