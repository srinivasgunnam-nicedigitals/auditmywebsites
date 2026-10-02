import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import re

async def debug_page(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print(f"Navigating to {url}...")
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"Goto error: {e}")

        rendered_html = None
        for content_retry in range(3):
            try:
                rendered_html = await page.content()
                if rendered_html: break
            except Exception as e:
                print(f"Content error ({content_retry}): {e}")
                await asyncio.sleep(2)
        
        if not rendered_html:
            print("Failed to get HTML")
            await browser.close()
            return
            
        soup = BeautifulSoup(rendered_html, "html.parser")
        header = soup.find('header')
        footer = soup.find('footer')
        
        header_text = header.get_text() if header else ""
        footer_text = footer.get_text() if footer else ""
        body_text = soup.body.get_text() if soup.body else ""
        full_text = soup.get_text(separator=" ", strip=True)
        
        print("\n--- Links found ---")
        for a in soup.find_all('a', href=True):
            if 'tel:' in a['href'] or 'callto:' in a['href']:
                print(a['href'], "->", a.get_text(strip=True))
                
        print("\n--- Regex matches ---")
        phone_pattern = re.compile(r'(?:\+?\d{1,3}[-.\s]*)?\(?\d{2,5}\)?[-.\s]*\d{2,5}[-.\s]*\d{4}(?:\s*(?:ext|x|#)\s*\d+)?')
        candidates = phone_pattern.findall(full_text)
        print(candidates)
        
        print("\n--- Check target numbers ---")
        print("432-8184 in full_text:", "432-8184" in full_text)
        print("717 in full_text:", "717" in full_text)
        
        if "432-8184" in full_text:
            idx = full_text.find("432-8184")
            print("Context of 432-8184:", full_text[max(0, idx-20):idx+20])
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_page("https://ourwebsitepreview.net/goldenrentals/about-us/"))
