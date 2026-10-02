import asyncio
from playwright.async_api import async_playwright

async def test_safari_qoder():
    url = "https://qoder.com"
    print(f"Testing Safari navigation to: {url}")
    
    async with async_playwright() as p:
        try:
            print("Launching Safari/WebKit...")
            browser = await p.webkit.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox", 
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--font-render-hinting=none",
                    "--disable-font-subpixel-positioning",
                    "--disable-remote-fonts"
                ]
            )
            print("Safari launched successfully!")
            
            # Create context with Safari-specific settings
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                viewport={"width": 1920, "height": 1080},
                bypass_csp=True,
                ignore_https_errors=True
            )
            
            page = await context.new_page()
            
            # Add font optimization
            await page.add_init_script("""() => {
                const style = document.createElement('style');
                style.textContent = `
                    * {
                        font-family: Arial, sans-serif !important;
                        font-display: swap !important;
                    }
                `;
                document.head.appendChild(style);
            }""")
            
            print("Navigating to URL...")
            try:
                # Try different navigation strategies
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                print(f"Initial navigation successful. Current URL: {page.url}")
                
                # Wait and check page status
                await page.wait_for_timeout(3000)
                
                # Check if page loaded properly
                title = await page.title()
                page_url = page.url
                print(f"Page title: {title}")
                print(f"Final URL: {page_url}")
                
                # Check for error conditions
                if page_url == "about:blank":
                    print("ERROR: Page is blank")
                    await page.screenshot(path="safari_qoder_blank.png")
                elif "error" in page_url.lower():
                    print("ERROR: Redirected to error page")
                    await page.screenshot(path="safari_qoder_error.png")
                else:
                    print("Page loaded successfully!")
                    await page.screenshot(path="safari_qoder_success.png", full_page=True)
                    
                    # Try to scroll and capture full page
                    try:
                        await page.evaluate("""async () => {
                            await new Promise((resolve) => {
                                let totalHeight = 0;
                                const distance = 800;
                                const timer = setInterval(() => {
                                    const scrollHeight = document.body.scrollHeight;
                                    window.scrollBy(0, distance);
                                    totalHeight += distance;
                                    if(totalHeight >= scrollHeight - window.innerHeight){
                                        clearInterval(timer);
                                        resolve();
                                    }
                                }, 150);
                            });
                        }""")
                        await page.wait_for_timeout(2000)
                        await page.evaluate("() => window.scrollTo(0, 0)")
                        await page.screenshot(path="safari_qoder_fullpage.png", full_page=True)
                        print("Full page screenshot captured!")
                    except Exception as scroll_error:
                        print(f"Scroll error: {scroll_error}")
                        await page.screenshot(path="safari_qoder_viewport.png", full_page=False)
                        
            except Exception as nav_error:
                print(f"Navigation error: {nav_error}")
                await page.screenshot(path="safari_qoder_nav_error.png")
                
        except Exception as e:
            print(f"Browser launch error: {e}")
        finally:
            try:
                await page.close()
                await context.close()
                await browser.close()
            except:
                pass

if __name__ == "__main__":
    asyncio.run(test_safari_qoder())