
import asyncio
import httpx
import xml.etree.ElementTree as ET
import re
from urllib.parse import urlparse, urljoin
import os

async def test_sitemap(url):
    print(f"Testing URL: {url}")
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
        try:
            resp = await client.get(url)
            print(f"Initial Status: {resp.status_code}")
            print(f"Initial Content-Type: {resp.headers.get('content-type')}")
            
            final_sitemap_url = url
            
            if "text/html" in resp.headers.get("content-type", "").lower():
                print("HTML detected, starting discovery...")
                parsed = urlparse(url)
                base_domain_url = f"{parsed.scheme}://{parsed.netloc}"
                path_dir = os.path.dirname(parsed.path) if '.' in os.path.basename(parsed.path) else parsed.path
                base_path_url = f"{parsed.scheme}://{parsed.netloc}{path_dir}".rstrip('/')
                
                guess_paths = ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml"]
                potential_urls = []
                for p in guess_paths:
                    potential_urls.append(f"{base_path_url}{p}")
                for p in guess_paths:
                    u = f"{base_domain_url}{p}"
                    if u not in potential_urls:
                        potential_urls.append(u)
                
                for test_url in potential_urls:
                    print(f"Trying guessed URL: {test_url}")
                    try:
                        test_resp = await client.get(test_url)
                        print(f"  Status: {test_resp.status_code}")
                        if test_resp.status_code == 200:
                            print(f"  Content-Type: {test_resp.headers.get('content-type')}")
                            if "xml" in test_resp.headers.get("content-type", "").lower() or b"<?xml" in test_resp.content[:100]:
                                print(f"  FOUND valid sitemap at: {test_url}")
                                resp = test_resp
                                final_sitemap_url = test_url
                                break
                    except Exception as e:
                        print(f"  Error trying {test_url}: {e}")

            # Now parse
            print(f"Parsing content from: {final_sitemap_url}")
            try:
                root = ET.fromstring(resp.content)
                ns = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                print(f"Namespace detected: {ns}")
                
                tag = root.tag.split('}')[-1]
                is_index = (tag == 'sitemapindex')
                print(f"Is Index: {is_index}")
                
                item_tag = 'sitemap' if is_index else 'url'
                item_selector = f'.//ns:{item_tag}' if ns else f'.//{item_tag}'
                
                items = root.findall(item_selector, ns)
                print(f"Found {len(items)} items using selector {item_selector}")
                
                for item in items[:5]:
                    def get_sub(parent, sub_tag):
                        return parent.find(f'ns:{sub_tag}', ns) if ns else parent.find(sub_tag)
                    loc = get_sub(item, 'loc')
                    print(f"  Location: {loc.text if loc is not None else 'N/A'}")
                    
            except Exception as e:
                print(f"Parsing Failed: {e}")
                import traceback
                traceback.print_exc()

        except Exception as e:
            print(f"Fatal Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_sitemap("https://ourwebsitepreview.net/goldenrentals"))
