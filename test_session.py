
import asyncio
import httpx

async def check_session():
    url = "https://ourwebsitepreview.net/goldenrentals"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    }
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False, headers=headers) as client:
        # First visit home to get cookies
        r1 = await client.get(url)
        print(f"Home Status: {r1.status_code}")
        
        # Then visit sitemap
        s_url = "https://ourwebsitepreview.net/goldenrentals/sitemap_index.xml"
        r2 = await client.get(s_url)
        print(f"Sitemap Status: {r2.status_code}")
        print(f"Sitemap Content (first 200): {r2.text[:200]}")

if __name__ == "__main__":
    asyncio.run(check_session())
