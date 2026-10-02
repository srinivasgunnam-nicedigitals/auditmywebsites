import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time

async def diagnostic():
    url = "https://ourwebsitepreview.net/goldenrentals/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    async with httpx.AsyncClient(verify=False, follow_redirects=True, headers=headers) as client:
        for attempt in range(3):
            print(f"\n--- Attempt {attempt + 1} ---")
            try:
                resp = await client.get(url)
                print(f"Status: {resp.status_code}")
                
                soup = BeautifulSoup(resp.text, 'html.parser')
                links = [a['href'] for a in soup.find_all('a', href=True)]
                print(f"Links found: {len(links)}")
                if links:
                    for l in links[:10]:
                        full = urljoin(url, l)
                        print(f"  {l} -> {full}")
                    break
                else:
                    print("No links found. Body snippet:")
                    print(resp.text[:500])
                
                if attempt < 2:
                    print("Waiting 3 seconds...")
                    await asyncio.sleep(3)
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(diagnostic())
