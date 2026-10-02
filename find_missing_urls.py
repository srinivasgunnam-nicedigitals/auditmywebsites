import models
from database import SessionLocal
import httpx
import asyncio
from xml.etree import ElementTree as ET

async def fetch_sitemap_urls_debug(start_url: str) -> set[str]:
    sitemap_urls_found = set()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False, headers=headers) as client:
        try:
            sitemap_paths = ["sitemap.xml", "sitemap_index.xml", "sitemap"]
            for sp in sitemap_paths:
                s_url = f"{start_url.rstrip('/')}/{sp}"
                try:
                    s_resp = await client.get(s_url, timeout=5.0)
                    if s_resp.status_code == 200:
                        root = ET.fromstring(s_resp.content)
                        namespaces = {'ns': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
                        locs = root.findall('.//ns:loc', namespaces) if namespaces else root.findall('.//loc')
                        for loc in locs:
                            loc_url = loc.text.strip()
                            if loc_url.endswith('.xml'):
                                try:
                                    c_resp = await client.get(loc_url, timeout=5.0)
                                    if c_resp.status_code == 200:
                                        c_root = ET.fromstring(c_resp.content)
                                        c_ns = {'ns': c_root.tag.split('}')[0].strip('{')} if '}' in c_root.tag else {}
                                        clocs = c_root.findall('.//ns:loc', c_ns) if c_ns else c_root.findall('.//loc')
                                        for cloc in clocs:
                                            sitemap_urls_found.add(cloc.text.strip())
                                except: pass
                            else:
                                sitemap_urls_found.add(loc_url)
                except: pass
        except: pass
    return sitemap_urls_found

def get_urls_from_db(session_id):
    db = SessionLocal()
    try:
        results = db.query(models.H1AuditResult).filter_by(session_id=session_id).all()
        return {r.url for r in results}
    finally:
        db.close()

async def compare():
    session_id = "h1_52dbab12"
    sitemap_urls = await fetch_sitemap_urls_debug("https://alulex.co.za")
    db_urls = get_urls_from_db(session_id)
    
    print(f"Sitemap count: {len(sitemap_urls)}")
    print(f"DB count: {len(db_urls)}")
    
    missing = sitemap_urls - db_urls
    print(f"Missing in DB ({len(missing)}):")
    for m in sorted(list(missing)):
        print(f"  {m}")
        
    extra = db_urls - sitemap_urls
    print(f"Extra in DB ({len(extra)}):")
    for e in sorted(list(extra)):
        print(f"  {e}")

if __name__ == "__main__":
    asyncio.run(compare())
