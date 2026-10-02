
import asyncio
from playwright.async_api import async_playwright

async def test_playwright():
    url = "https://ourwebsitepreview.net/goldenrentals/sitemap_index.xml"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        print(f"Loading {url}...")
        try:
            # Wait for network idle to ensure captcha/refresh is done
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            print(f"Status: {response.status}")
            content = await page.content()
            print(f"Content (first 200): {content[:200]}")
            
            # For XML, Playwright wrap it in a <pre> or similar if viewed as HTML
            # We want the raw response body
            body = await page.evaluate("() => document.body.innerText")
            print(f"Body Text (first 200): {body[:200]}")
            
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_playwright())
