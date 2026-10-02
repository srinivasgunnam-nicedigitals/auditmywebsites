import asyncio
from playwright.async_api import async_playwright
import os

async def verify_popup():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Step 1: Register or Login
        print("Navigating to register...")
        await page.goto("http://localhost:8001/register")
        email = "verify_popup_final@example.com"
        await page.fill('input[name="full_name"]', "Verify Popup")
        await page.fill('input[name="email"]', email)
        await page.fill('input[name="password"]', "Password123!")
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/dashboard")
        print("Registered and logged in.")

        # Step 2: Set credits to 50
        print("Setting credits to 50...")
        from database import SessionLocal
        from models import User
        db = SessionLocal()
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.credits = 50
            user.low_credit_notified = False
            db.commit()
            print("Credits set to 50.")
        db.close()
        
        # Step 3: Trigger H1 audit
        print("Navigating to H1 audit...")
        await page.goto("http://localhost:8001/h1-audit")
        await page.fill('input[name="session_name"]', "Test Popup Project")
        await page.fill('input[name="url"]', "https://example.com")
        
        print("Starting audit...")
        await page.click('button.btn-primary') # Start button
        
        # Step 4: Wait for popup
        print("Waiting for popup...")
        # The showAlert uses #confirm-modal
        try:
            await page.wait_for_selector('#confirm-modal', state='visible', timeout=10000)
            print("Popup appeared!")
            await asyncio.sleep(1) # Wait for animation
            await page.screenshot(path="low_credit_popup_verified.png")
            print("Screenshot captured: low_credit_popup_verified.png")
        except Exception as e:
            print(f"Popup did not appear or timed out: {e}")
            await page.screenshot(path="popup_failure.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(verify_popup())
