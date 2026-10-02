import asyncio
import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from routers.image_alt import crawl_site_bfs

async def main():
    urls = await crawl_site_bfs('https://www.nicedigitals.com', max_pages=300, max_time=30)
    print('Total found:', len(urls))
    for i, u in enumerate(urls[:20]):
        print(f"[{i}]: {u}")

asyncio.run(main())
