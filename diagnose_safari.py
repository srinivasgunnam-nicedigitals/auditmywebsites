import asyncio
from playwright.async_api import async_playwright

async def diagnose_safari_issues():
    """Diagnostic script to identify specific Safari issues"""
    
    test_urls = [
        "https://qoder.com",
        "https://example.com", 
        "https://google.com"
    ]
    
    print("=== Safari/WebKit Diagnostic Test ===\n")
    
    async with async_playwright() as p:
        try:
            print("1. Browser Launch Test...")
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
            print("✓ Safari launched successfully")
            
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
                bypass_csp=True,
                ignore_https_errors=True
            )
            
            for i, url in enumerate(test_urls, 1):
                print(f"\n2. Testing URL {i}: {url}")
                page = await context.new_page()
                
                try:
                    # Test navigation
                    print("   → Navigation test...")
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(2000)
                    
                    # Check page status
                    current_url = page.url
                    title = await page.title()
                    print(f"   ✓ Navigation successful")
                    print(f"   ✓ Current URL: {current_url}")
                    print(f"   ✓ Page title: {title}")
                    
                    # Test screenshot
                    print("   → Screenshot test...")
                    screenshot_path = f"diagnostic_safari_{i}.png"
                    await page.screenshot(path=screenshot_path, full_page=True, timeout=15000)
                    print(f"   ✓ Screenshot saved: {screenshot_path}")
                    
                except Exception as e:
                    print(f"   ✗ Error: {e}")
                    # Create error screenshot
                    error_path = f"diagnostic_safari_{i}_error.png"
                    from PIL import Image, ImageDraw
                    error_img = Image.new('RGB', (800, 600), color=(50, 30, 30))
                    draw = ImageDraw.Draw(error_img)
                    draw.text((50, 50), f"Error testing {url}", fill=(200, 100, 100))
                    draw.text((50, 100), f"Error: {str(e)[:100]}", fill=(180, 180, 180))
                    error_img.save(error_path)
                    print(f"   → Error screenshot: {error_path}")
                
                finally:
                    await page.close()
            
            await context.close()
            await browser.close()
            print("\n=== Diagnostic Complete ===")
            
        except Exception as e:
            print(f"Browser launch failed: {e}")

if __name__ == "__main__":
    asyncio.run(diagnose_safari_issues())