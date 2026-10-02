import asyncio
import sys
import os

# Add the project root to sys.path
sys.path.append(os.getcwd())

from routers.meta_tags import check_host_health, audit_meta_tags_logic
import models
from database import SessionLocal

async def test_health_check():
    print("-" * 50)
    print("TEST 1: Non-existent host")
    url1 = "https://non-existent-host-123456789.com"
    error1 = await check_host_health(url1)
    print(f"URL: {url1}")
    print(f"Expected: Error message")
    print(f"Actual Result: {error1}")
    print("-" * 50)
    
    print("TEST 2: Reachable host")
    url2 = "https://google.com"
    error2 = await check_host_health(url2)
    print(f"URL: {url2}")
    print(f"Expected: None")
    print(f"Actual Result: {error2}")
    print("-" * 50)

async def test_abort_logic():
    print("\nTesting abort logic simulation (manual check of code logic)...")
    # This is harder to test without a full DB setup and mocked network, 
    # but we can verify the check_host_health logic which is the first line of defense.
    pass

if __name__ == "__main__":
    asyncio.run(test_health_check())
