import asyncio
from playwright.async_api import async_playwright

async def test_webkit():
    try:
        async with async_playwright() as p:
            print("Available browsers:")
            print(f"  Chromium: {p.chromium}")
            print(f"  Firefox: {p.firefox}")
            print(f"  WebKit: {p.webkit}")
            
            print("\nTesting WebKit launch...")
            browser = await p.webkit.launch(headless=True)
            print("WebKit launched successfully!")
            
            context = await browser.new_context()
            page = await context.new_page()
            
            await page.goto("https://example.com")
            print(f"Page loaded: {page.url}")
            
            await page.screenshot(path="test_webkit_screenshot.png", full_page=True)
            print("Screenshot captured successfully!")
            
            await page.close()
            await context.close()
            await browser.close()
            print("All operations completed successfully!")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_webkit())