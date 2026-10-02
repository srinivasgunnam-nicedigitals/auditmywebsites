import asyncio
import httpx
import re
import xml.etree.ElementTree as ET

URL = "https://jafarilawgroup.com/sitemap_index.xml" # Guessing the live equivalent, or I'll try the dev one if I can.
# The user's screenshot had "jafari/demo", implying a staging site. 
# But let's try the live one closely matching the previous context "jafarilawgroup.com".
# Actually, the user's screenshot 1 shows "https://dev.pointclick.io/jafari/demo/sitemap_index.xml"
# I will try that one.

TARGET_URL = "https://dev.pointclick.io/jafari/demo/sitemap_index.xml"

async def test_parse():
    print(f"Fetching {TARGET_URL}...")
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        try:
            resp = await client.get(TARGET_URL, timeout=30)
            print(f"Status: {resp.status_code}")
            if resp.status_code != 200:
                print("Failed to fetch.")
                return

            xml_content = resp.text
            print(f"Content length: {len(xml_content)}")
            print(f"First 200 chars: {xml_content[:200]}")

            # CURRENT LOGIC FROM routers/sitemaps.py
            try:
                # Simple namespace stripping for easier parsing
                # xml_content_stripped = re.sub(r' xmlns="[^"]+"', '', xml_content, count=1)
                # The code in sitemaps.py:
                xml_content_stripped = re.sub(r' xmlns="[^"]+"', '', xml_content, count=1)
                
                root = ET.fromstring(xml_content_stripped.encode('utf-8'))
                
                tag = root.tag.split('}')[-1]
                is_index = (tag == 'sitemapindex')
                print(f"Is Index: {is_index}")
                print(f"Root tag: {root.tag}")

                item_tag = 'sitemap' if is_index else 'url'
                items = root.findall(f'.//{item_tag}')
                print(f"Found {len(items)} items using logic 1.")
                
            except Exception as e:
                print(f"Logic 1 Failed: {e}")

        except Exception as e:
            print(f"Request Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_parse())
