"""
ph.py - Diagnostic phone number crawl tool.
Mirrors the production logic in routers/phone.py exactly.
"""
import asyncio
import re
import sys
from urllib.parse import urlparse

from playwright.async_api import async_playwright
import phonenumbers

START_URL = "https://ourwebsitepreview.net/goldenrentals"
MAX_PAGES = 100
MAX_WORKERS = 5

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
BROWSER_ARGS = ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']

def normalize_phone(num: str) -> str:
    return "".join(c for c in num if c.isdigit())

def find_phones_in_text(text: str, region: str = "US") -> set:
    phones = set()
    if not text:
        return phones
    try:
        for match in phonenumbers.PhoneNumberMatcher(text, region):
            formatted = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.NATIONAL)
            phones.add(formatted)
    except Exception:
        pass
    pattern = r'(?:\+?\d{1,3}[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}'
    for m in re.findall(pattern, text):
        m = m.strip()
        if m and len(normalize_phone(m)) >= 7:
            phones.add(m)
    return phones

async def navigate_page(page, url: str) -> bool:
    try:
        response = await page.goto(url, wait_until="load", timeout=90000)
        if response and (response.status == 202 or "sg-captcha" in response.headers):
            print(f"  [challenge] WAF on {url}, waiting 15s...")
            await page.wait_for_timeout(15000)
            content = await page.content()
            if 'http-equiv="refresh"' in content:
                print(f"  [challenge] Still refreshing, waiting 10s more...")
                await page.wait_for_timeout(10000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
        return True
    except Exception as e:
        print(f"  [nav error] {url}: {e}")
        return False

async def extract_phones_from_page(page) -> set:
    phones = set()
    async def safe_eval(expr):
        for attempt in range(3):
            try:
                return await page.evaluate(expr)
            except Exception as e:
                if "context was destroyed" in str(e) and attempt < 2:
                    await asyncio.sleep(1.5)
                    continue
                raise
    try:
        data = await safe_eval('''() => {
            return {
                text: document.body ? document.body.innerText : '',
                links: Array.from(document.querySelectorAll('a')).map(a => ({
                    href: a.getAttribute('href') || '',
                    text: a.innerText || ''
                })),
                metas: Array.from(document.querySelectorAll('meta')).map(m => ({
                    name: (m.getAttribute('name') || m.getAttribute('property') || '').toLowerCase(),
                    content: m.getAttribute('content') || ''
                })),
                jsonld: Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => s.innerText)
            };
        }''')
    except Exception as e:
        print(f"  [extract error] {e}")
        return phones

    for p in find_phones_in_text(data.get('text', '')):
        phones.add(p)
    for link in data.get('links', []):
        href = link.get('href', '')
        text = link.get('text', '')
        if href.lower().startswith('tel:'):
            tel = href[4:].split('?')[0].strip()
            if tel:
                phones.add(tel)
        for p in find_phones_in_text(text):
            phones.add(p)
    for meta in data.get('metas', []):
        name = meta.get('name', '')
        content = meta.get('content', '')
        if any(x in name for x in ['phone', 'tel', 'contact', 'telephone']) and content:
            for p in find_phones_in_text(content):
                phones.add(p)
    for ld in data.get('jsonld', []):
        try:
            for p in find_phones_in_text(ld):
                phones.add(p)
        except Exception:
            pass
    return phones


async def main():
    base_domain = urlparse(START_URL).netloc
    visited = set()
    url_queue = asyncio.Queue()
    await url_queue.put(START_URL)
    results = {}  # url -> set of phones

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800}
        )

        async def worker():
            page = await context.new_page()
            try:
                while True:
                    # Blocking wait — never exits early while other workers await WAF
                    url = await url_queue.get()

                    # Sentinel: time to stop
                    if url is None:
                        url_queue.task_done()
                        break

                    if url in visited:
                        url_queue.task_done()
                        continue

                    if any(x in url for x in ['get=sound', '.mp3', '.wav']):
                        print(f"  [skip] {url}")
                        url_queue.task_done()
                        continue

                    visited.add(url)
                    print(f"Crawling: {url} (Total: {len(visited)})")

                    success = await navigate_page(page, url)
                    if not success:
                        url_queue.task_done()
                        continue

                    # Extract phones on this page
                    phones = await extract_phones_from_page(page)
                    if phones:
                        results[url] = phones
                        for phone in phones:
                            print(f"  [FOUND] {phone}")

                    # Queue links
                    try:
                        links = await page.evaluate(
                            "Array.from(document.querySelectorAll('a')).map(e => e.href)"
                        )
                        for link in links:
                            if not link or not isinstance(link, str):
                                continue
                            clean = link.split('#')[0].strip()
                            if not clean:
                                continue
                            parsed = urlparse(clean)
                            if parsed.netloc == base_domain and clean not in visited:
                                if not any(clean.lower().endswith(ext) for ext in [
                                    '.jpg', '.jpeg', '.png', '.gif', '.pdf', '.css',
                                    '.js', '.zip', '.xml', '.json', '.svg', '.ico',
                                    '.mp4', '.webp', '.woff', '.woff2', '.mp3', '.wav'
                                ]):
                                    if len(visited) < MAX_PAGES:
                                        await url_queue.put(clean)
                    except Exception as e:
                        print(f"  [link error] {url}: {e}")

                    url_queue.task_done()

            except Exception as e:
                print(f"  [worker fatal] {e}")
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        workers = [asyncio.create_task(worker()) for _ in range(MAX_WORKERS)]

        # Wait for ALL urls (including WAF-delayed ones) to complete
        await url_queue.join()

        # Signal each worker to stop cleanly
        for _ in range(MAX_WORKERS):
            await url_queue.put(None)

        await asyncio.gather(*workers, return_exceptions=True)
        await browser.close()

    print(f"\n========== RESULTS ==========")
    print(f"URLs crawled:  {len(visited)}")
    print(f"URLs with phones: {len(results)}")
    print()
    for url, phones in results.items():
        print(f"{url}")
        for phone in phones:
            norm = normalize_phone(phone)
            print(f"  -> {phone}  (digits: {norm})")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())