import httpx
import asyncio

async def check():
    url = "https://www.alulex.co.za"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient(verify=False, follow_redirects=True, headers=headers) as client:
        try:
            resp = await client.get(url)
            print(f"URL: {url}")
            print(f"Status: {resp.status_code}")
            print(f"Final URL: {resp.url}")
            print(f"Content Length: {len(resp.content)}")
            print(f"Headers: {dict(resp.headers)}")
            
            sitemap_url = "https://www.alulex.co.za/sitemap.xml"
            s_resp = await client.get(sitemap_url)
            print(f"\nSitemap: {sitemap_url}")
            print(f"Status: {s_resp.status_code}")
            if s_resp.status_code == 200:
                print(f"Sitemap Content Type: {s_resp.headers.get('Content-Type')}")
                from xml.etree import ElementTree as ET
                try:
                    root = ET.fromstring(s_resp.content)
                    print(f"Root tag: {root.tag}")
                    namespaces = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                    locs = root.findall('.//ns:loc', namespaces) if namespaces else root.findall('.//loc')
                    print(f"Found {len(locs)} loc elements")
                    for loc in locs[:5]:
                        print(f"  Loc: {loc.text}")
                        if loc.text.strip().endswith('.xml'):
                            c_resp = await client.get(loc.text.strip())
                            print(f"    Sub-sitemap status: {c_resp.status_code}")
                            if c_resp.status_code == 200:
                                c_root = ET.fromstring(c_resp.content)
                                c_ns = {'ns': c_root.tag.split('}')[0].strip('{')} if '}' in c_root.tag else {}
                                c_locs = c_root.findall('.//ns:loc', c_ns) if c_ns else c_root.findall('.//loc')
                                print(f"    Found {len(c_locs)} sub-loc elements")
                except Exception as e:
                    print(f"Sitemap parse error: {e}")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
