import os
import re

# The Pattern that we suspect is in the files now (WITH the bad style)
BAD_PATTERN_REGEX = re.compile(r'(<a href="/platform/profile" class="nav-item">\s*<svg[^>]+style="margin-right: 0.75rem;">.*?</svg>\s*<span>Profile</span>\s*</a>)', re.DOTALL)

# The CORRECTED block (With class="icon" and NO inline style)
CORRECTED_BLOCK = """<a href="/platform/profile" class="nav-item">
             <svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
            <span>Profile</span>
        </a>"""

base_dir = r"c:\Users\user\Downloads\newuisite\templates"

# We should check ALL html files now
count = 0
for filename in os.listdir(base_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check if file has the BAD sidebar pattern
        new_content = BAD_PATTERN_REGEX.sub(CORRECTED_BLOCK, content)
            
        if new_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"Corrected {filename}")
            count += 1
        else:
            # Also check if it lacked the profile link entirely and run the ORIGINAL insertion but with the CORRECT block
            pass # We assume the previous run added it to all, so we just focus on fixing the bad ones.

print(f"Total corrected: {count}")
