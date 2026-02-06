import asyncio
from playwright.async_api import async_playwright

async def run():
    url = "https://ourwebsitepreview.net/millbraelock/"
    print(f"Testing URL: {url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        try:
            print("Navigating...")
            # MATCHING THE NEW LOGIC IN MAIN.PY
            try:
                await page.goto(url, wait_until="networkidle", timeout=45000)
            except Exception as e:
                print(f"Network idle timeout, fallback: {e}")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            print("Waiting for selector 'h1'...")
            try:
                await page.wait_for_selector("h1", timeout=5000)
                print("Selector 'h1' found!")
            except:
                print("Selector 'h1' NOT found (timeout)")

            print("Waiting buffer 2s...")
            await page.wait_for_timeout(2000)
            
            h1_data = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('h1')).map(el => ({
                    text: el.innerText.trim(),
                    length: el.innerText.trim().length,
                    html: el.outerHTML,
                    visible: (el.offsetWidth > 0 && el.offsetHeight > 0)
                }));
            }""")
            
            print(f"Found {len(h1_data)} H1 tags.")
            for i, h1 in enumerate(h1_data):
                print(f"H1 #{i+1}: Text='{h1['text']}', Visible={h1['visible']}")

        except Exception as e:
            print(f"Error: {e}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
