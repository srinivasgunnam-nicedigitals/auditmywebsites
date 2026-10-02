import asyncio
from playwright.async_api import async_playwright
import re

async def test_phone_detection():
    url = "https://ourwebsitepreview.net/goldenrentals/used-equipment-sales/"
    async with async_playwright() as p:
        print(f"Opening {url}...")
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(2)
        
        full_text = await page.evaluate("() => document.body.innerText")
        print(f"Page text length: {len(full_text)}")
        
        phone_pattern = re.compile(r'(?:\+?\d{1,3}[-.\s]*)?\(?\d{2,5}\)?[-.\s]*\d{2,5}[-.\s]*\d{4}(?:\s*(?:ext|x|#)\s*\d+)?')
        candidates = phone_pattern.findall(full_text)
        
        print(f"Candidates found: {candidates}")
        target = "(717) 432-8184"
        if any(target in c for c in candidates):
            print("SUCCESS: Phone number detected!")
        else:
            print("FAILURE: Phone number NOT detected.")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test_phone_detection())
