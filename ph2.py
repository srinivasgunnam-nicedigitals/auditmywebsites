import asyncio
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

start_url = "https://ourwebsitepreview.net/goldenrentals/"
domain = urlparse(start_url).netloc

visited = set()
queue = asyncio.Queue()

phone_pattern = re.compile(r'(\+?\d[\d\-\(\) ]{7,}\d)')


async def extract_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for a in soup.find_all("a", href=True):
        link = urljoin(base, a["href"])
        if urlparse(link).netloc == domain:
            links.add(link)

    return links


async def extract_phones(text):
    return set(phone_pattern.findall(text))


async def fetch_html(client, url):
    try:
        r = await client.get(url, timeout=10)
        return r.text
    except:
        return ""


async def render_page(page, url):
    try:
        await page.goto(url, wait_until="networkidle")
        return await page.content()
    except:
        return ""


async def worker(client, page):
    while True:
        url = await queue.get()

        if url in visited:
            queue.task_done()
            continue

        visited.add(url)

        print("Crawling:", url)

        html = await fetch_html(client, url)

        phones = await extract_phones(html)

        if phones:
            print("Phones:", phones)

        # Render page to get dynamic links
        rendered_html = await render_page(page, url)

        links = await extract_links(rendered_html, url)

        for link in links:
            if link not in visited:
                await queue.put(link)

        # Extract phones from rendered page
        js_phones = await extract_phones(rendered_html)

        if js_phones:
            print("JS Phones:", js_phones)

        queue.task_done()


async def main():
    await queue.put(start_url)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            tasks = []
            for _ in range(5):
                tasks.append(asyncio.create_task(worker(client, page)))

            await queue.join()

            for t in tasks:
                t.cancel()

            await browser.close()


asyncio.run(main())