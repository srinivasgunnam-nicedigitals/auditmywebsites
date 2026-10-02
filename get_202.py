import httpx

def get_202():
    url = "https://ourwebsitepreview.net/goldenrentals/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(verify=False, follow_redirects=True, headers=headers) as client:
        r = client.get(url)
        print(f"Status: {r.status_code}")
        print(f"Headers: {dict(r.headers)}")
        with open('202_response.html', 'w', encoding='utf-8') as f:
            f.write(r.text)
        print("Wrote to 202_response.html")

if __name__ == "__main__":
    get_202()
