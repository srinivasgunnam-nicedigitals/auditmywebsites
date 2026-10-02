import os
import re

templates_dir = r"c:\Users\user\Downloads\newuisite - Copy\templates"

# Mapping of filename keyword/exact to the href that should be active
mapping = {
    "dashboard.html": "/platform/dashboard",
    "static.html": "/platform/static",
    "device_lab.html": "/platform/device-lab",
    "performance_audit.html": "/platform/performance",
    "accessibility_audit.html": "/platform/accessibility",
    "phone_validator.html": "/phone-audit",
    "h1_tags.html": "/h1-audit",
    "metatags.html": "/scan/meta-tags",
    "sitemaps.html": "/scan/xml-sitemaps",
    "profile.html": "/platform/profile",
    "audit_history.html": "/platform/history",
    "history.html": "/platform/history", # Catches all *_history.html
    "static_snapshots.html": "/responsive",
}

for filename in os.listdir(templates_dir):
    if not filename.endswith(".html"):
        continue
    
    path = os.path.join(templates_dir, filename)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Target href for this file
    target_href = None
    if filename in mapping:
        target_href = mapping[filename]
    else:
        # Fallback for history files
        if "history.html" in filename:
            target_href = "/platform/history"
        elif "report.html" in filename:
            # Reports might not have a sidebar active, or maybe they should show the tool active
            if "performance" in filename: target_href = "/platform/performance"
            elif "accessibility" in filename: target_href = "/platform/accessibility"
            elif "static" in filename: target_href = "/platform/static"
            elif "h1" in filename: target_href = "/h1-audit"
            elif "phone" in filename: target_href = "/phone-audit"
            elif "meta" in filename: target_href = "/scan/meta-tags"
            elif "sitemap" in filename: target_href = "/scan/xml-sitemaps"

    if not target_href:
        continue

    # First, remove 'active' from all nav-items
    # Use regex to find nav-items and remove 'active' class
    # Matches: class="nav-item active" or class="active nav-item" or class="nav-item  active"
    content = re.sub(r'class="nav-item\s+active"', 'class="nav-item"', content)
    content = re.sub(r'class="active\s+nav-item"', 'class="nav-item"', content)
    
    # Now add 'active' to the target href
    # We want to match <a href="TARGET" class="nav-item">
    # Note: the target_href might be slightly different in the template (e.g. with/without trailing slash)
    # But let's assume exact match for now as they are pretty consistent
    
    pattern = re.compile(f'href="{re.escape(target_href)}"[^>]*class="nav-item"', re.IGNORECASE)
    
    if pattern.search(content):
        new_content = pattern.sub(f'href="{target_href}" class="nav-item active"', content)
        if new_content != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Fixed active state in {filename} for {target_href}")
    else:
        print(f"Could not find nav link for {target_href} in {filename}")

print("Done.")
