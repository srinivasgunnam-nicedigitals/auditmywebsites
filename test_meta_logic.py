import json
from urllib.parse import urlparse

# Simulation of the logic I added to meta_tags.py

def test_is_comparison(urls):
    unique_domains = set()
    for u in urls:
        try:
            netloc = urlparse(u).netloc
            # Logic: remove www.
            netloc = netloc.replace("www.", "")
            unique_domains.add(netloc)
        except: pass
        
    is_comparison = len(unique_domains) == 2
    return is_comparison, unique_domains

# Scenarios
scenarios = [
    {
        "name": "Single Site Crawl (Many pages, same domain)",
        "urls": [
            "https://example.com",
            "https://example.com/page1",
            "https://example.com/about",
            "https://example.com/contact"
        ],
        "expected": False
    },
    {
        "name": "Comparison (Live vs Staging, different domains)",
        "urls": [
            "https://example.com",
            "https://staging.example.com",
            "https://example.com/page1",
            "https://staging.example.com/page1"
        ],
        "expected": True
    },
    {
        "name": "Single Site with www mix (Should be Single Site now)",
        "urls": [
            "https://example.com",
            "https://www.example.com"
        ],
        "expected": False 
    },
    {
        "name": "Bulk Audit (3+ Domains)",
        "urls": [
            "https://site1.com",
            "https://site2.com",
            "https://site3.com"
        ],
        "expected": False
    }
]

print("Running Logic Verification...")
for s in scenarios:
    result, domains = test_is_comparison(s["urls"])
    pass_fail = "PASS" if result == s["expected"] else "FAIL"
    print(f"Scenario: {s['name']}")
    print(f"  URLs: {len(s['urls'])}")
    print(f"  Domains Found: {domains}")
    print(f"  Expected is_comparison: {s['expected']}")
    print(f"  Actual is_comparison:   {result}")
    print(f"  Result: {pass_fail}")
    print("-" * 30)
