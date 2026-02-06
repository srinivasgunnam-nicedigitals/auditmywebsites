import os
import re

# The Pattern that we suspect is in the files now (class="icon")
# We want to change the SVG to use stroke="#9CA3AF" (or whatever the inactive color is) instead of currentColor, OR just enforce a style class that doesn't inherit color.
# The inactive color in CSS is #9CA3AF. The active color is var(--primary-blue).
# The user wants it "similar to other symbols". Other symbols are images, so they probably stay their original color (likely white or grey).
# If I change stroke="currentColor" to stroke="#9CA3AF", it will stay grey even when active.
# However, if the user wants it white, I should use white.
# Let's assume the icon should act like the others.
# If I use stroke="#9CA3AF" it will be grey.
# Let's try to find what the other icons are.
# But for now, to fix the "blue" issue, removing currentColor is key.

# Corrected block with explicit color (or class that handles it). 
# I will use a class .profile-icon and style it in CSS if I can, but I can't easily edit CSS across artifacts without appending.
# Simple fix: Use hardcoded stroke color that matches the inactive state common color.
# Inactive nav-item color is #9CA3AF.
# But wait, usually icons are White or Light Grey.
# Let's use stroke="#D1D5DB" (light grey) or just remove stroke="currentColor" and set stroke="#9CA3AF".

BAD_PATTERN_REGEX = re.compile(r'(<a href="/platform/profile" class="nav-item[^"]*">\s*<svg class="icon"[^>]+>.*?</svg>\s*<span>Profile</span>\s*</a>)', re.DOTALL)

# Note: I'm replacing the whole block, ensuring it has the right structure.
# I'll use a style attribute to force the color to text-secondary equivalent or white, effectively ignoring the parent's blue active color.
CORRECTED_BLOCK = """<a href="/platform/profile" class="nav-item">
             <svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
            <span>Profile</span>
        </a>"""

base_dir = r"c:\Users\user\Downloads\newuisite\templates"

count = 0
for filename in os.listdir(base_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check if file has the sidebar pattern
        # We need to match loose variations of class="nav-item" or "nav-item active"
        # The regex above expects "nav-item" OR "nav-item active" etc via [^"]*
        
        match = BAD_PATTERN_REGEX.search(content)
        if match:
             # Preserve the active class if it was there?
             # The regex captures the whole tag.
             # If I replace it with the generic one, I lose "active" if it was active (like in profile.html).
             # So I should be careful.
             
             # BETTER APPROACH: Just replace the SVG line.
             pass

# Let's rewrite loop to be safer.
for filename in os.listdir(base_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        # We look for the SVG with class="icon" inside profile link
        # And replace stroke="currentColor" with stroke="#9CA3AF"
        # This is safer than replacing the whole block.
        
        # Regex to find the specific SVG for profile
        # We look for the profile text, then look backwards? No.
        # We look for the <a href="/platform/profile"...> then the SVG.
        
        # Simplify: search/replace the specific string of the SVG if it's unique enough.
        # The SVG path is unique: <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle>
        
        target_svg_start = '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
        replacement_svg_start = '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF"'
        
        if target_svg_start in content and "/platform/profile" in content:
             new_content = content.replace(target_svg_start, replacement_svg_start)
             if new_content != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"Corrected {filename}")
                count += 1

print(f"Total corrected: {count}")
