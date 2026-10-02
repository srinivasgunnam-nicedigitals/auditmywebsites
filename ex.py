import asyncio
from playwright.async_api import async_playwright
from urllib.parse import urlparse

start_url = "https://rossdownslaw.bwpsites.com/"
domain = urlparse(start_url).netloc

visited = set()
queue = asyncio.Queue()

MAX_WORKERS = 10


async def worker(browser):
    page = await browser.new_page()

    while True:
        url = await queue.get()

        if url in visited:
            queue.task_done()
            continue

        visited.add(url)

        try:
            print("Crawling:", url)

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            h1 = await page.locator("h1").all_inner_texts()

            print("H1:", h1)

            links = await page.locator("a").evaluate_all(
                "els => els.map(e => e.href)"
            )

            for link in links:
                parsed = urlparse(link)

                if parsed.netloc == domain and link not in visited:
                    await queue.put(link)

        except Exception as e:
            print("Error:", e)

        queue.task_done()


async def crawl():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        await queue.put(start_url)

        tasks = []

        for _ in range(MAX_WORKERS):
            tasks.append(asyncio.create_task(worker(browser)))

        await queue.join()

        for task in tasks:
            task.cancel()

        await browser.close()

    print("\nTotal URLs crawled:", len(visited))


asyncio.run(crawl())