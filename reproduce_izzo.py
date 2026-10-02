
import asyncio
import os
from playwright.async_api import async_playwright

async def reproduce():
    url = "https://www.izzoassociateslaw.com/"
    print(f"Testing URL: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Try different user agents or contexts if needed
        context_args = {
            "viewport": {"width": 1280, "height": 720},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "ignore_https_errors": True
        }
        
        context = await browser.new_context(**context_args)
        page = await context.new_page()
        
        try:
            print("Attempting to navigate to the page...")
            # Use same wait_until as in responsive.py
            response = await page.goto(url, wait_until="load", timeout=90000)
            
            try:
                print("Waiting for network idle (capped at 10s)...")
                await page.wait_for_load_state("networkidle", timeout=10000)
            except:
                print("Network idle timeout reached (continuing anyway).")
            
            if response:
                print(f"Response status: {response.status}")
                print(f"Response headers: {response.headers}")
            else:
                print("No response received.")
            
            await page.wait_for_timeout(3000)
            
            # Try to take a screenshot
            screenshot_path = "izzo_test.png"
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"Screenshot saved to {screenshot_path}")
            
            content = await page.content()
            print(f"Content length: {len(content)}")
            if len(content) < 500:
                 print(f"Content: {content}")

        except Exception as e:
            print(f"Error during navigation/screenshot: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(reproduce())
