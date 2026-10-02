
import httpx
import asyncio

async def test_proxy():
    url = "https://www.izzoassociateslaw.com/"
    proxy_url = f"http://localhost:8001/api/proxy?url={url}" # Assuming uvicorn is running on 8001
    
    print(f"Testing Proxy for: {url}")
    print(f"Proxy URL: {proxy_url}")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            # Note: I need to make sure uvicorn is actually running and accessible.
            # The metadata says: uvicorn main:app --host 0.0.0.0 --port 8001 --reload 
            response = await client.get(proxy_url)
            print(f"Proxy Response Status: {response.status_code}")
            # print(f"Proxy Response Headers: {response.headers}")
            content_preview = response.text[:500]
            print(f"Content Preview: {content_preview}")
            
            if "Unable to Load Site" in response.text:
                print("FAILED: Proxy returned 'Unable to Load Site' error page.")
            elif "bot protection" in response.text.lower():
                print("FAILED: Bot protection detected.")
            else:
                print("SUCCESS: Proxy seems to have fetched the content.")
                
        except Exception as e:
            print(f"Proxy Request Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_proxy())
