import os
import re

TERM = """
        <div class="nav-section-title">Platform</div>
        <a href="/platform/dashboard"
"""

REPLACEMENT = """
        <div class="nav-section-title">Platform</div>
        <a href="/platform/profile" class="nav-item">
             <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.75rem;"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
            <span>Profile</span>
        </a>
        <a href="/platform/dashboard"
"""

# Normalize whitespace for regex
# We want to match "Platform</div>" followed by whitespace followed by "<a href="/platform/dashboard""
regex_pattern = re.compile(r'(<div class="nav-section-title">Platform</div>\s+<a href="/platform/dashboard")', re.MULTILINE)

replacement_str = """<div class="nav-section-title">Platform</div>
        <a href="/platform/profile" class="nav-item">
             <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 0.75rem;"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
            <span>Profile</span>
        </a>
        <a href="/platform/dashboard" """

base_dir = r"c:\Users\user\Downloads\newuisite\templates"

# Files to skip (profile.html already has it, dashboard.html already has it)
skip_files = ["profile.html", "dashboard.html"]

count = 0
for filename in os.listdir(base_dir):
    if filename.endswith(".html") and filename not in skip_files:
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check if file has the sidebar pattern
        if "id=\"sidebar-toggle\"" in content and "href=\"/platform/profile\"" not in content:
            # It has sidebar but NO profile link
            new_content = regex_pattern.sub(replacement_str, content)
            
            if new_content != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"Updated {filename}")
                count += 1
            else:
                print(f"Pattern not found in {filename}")

print(f"Total updated: {count}")
