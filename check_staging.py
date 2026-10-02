
import asyncio
import httpx

async def check_content():
    url = "https://ourwebsitepreview.net/goldenrentals"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=False) as client:
        resp = await client.get(url)
        print(f"Status: {resp.status_code}")
        print(f"Headers: {dict(resp.headers)}")
        print(f"Content (first 500 chars): {resp.text[:500]}")

if __name__ == "__main__":
    asyncio.run(check_content())
