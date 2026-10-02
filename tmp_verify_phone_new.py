import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

async def test_extraction():
    url = "https://ourwebsitepreview.net/goldenrentals/outdoor-movie-screens/"
    async with async_playwright() as p:
        print(f"Opening {url}...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)
        
        html = await page.content()
        soup = BeautifulSoup(html, "html.parser")
        
        full_text = soup.get_text(separator=" ", strip=True)
        print(f"Page text length: {len(full_text)}")
        
        # Check Links
        links = []
        for a in soup.find_all('a', href=True):
            if a['href'].startswith(('tel:', 'callto:')):
                links.append(a['href'])
        print(f"Tel links found: {links}")
        
        # Check Regex
        phone_pattern = re.compile(r'(?:\+?\d{1,3}[-.\s]*)?\(?\d{2,5}\)?[-.\s]*\d{2,5}[-.\s]*\d{4}(?:\s*(?:ext|x|#)\s*\d+)?')
        candidates = phone_pattern.findall(full_text)
        print(f"Regex candidates found: {candidates}")
        
        target = "432-8184"
        if any(target in str(l) for l in links) or any(target in c for c in candidates):
            print("SUCCESS: Phone number detected!")
        else:
            print("FAILURE: Phone number NOT detected.")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_extraction())
