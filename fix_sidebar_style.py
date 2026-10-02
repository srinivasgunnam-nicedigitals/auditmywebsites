import os
import re

# We want to add style="stroke: #9CA3AF !important;" to the SVG.
# The current state in files is likely: stroke="#9CA3AF"
# We want to replace it with: stroke="#9CA3AF" style="stroke: #9CA3AF !important;"
# Or just replace the whole SVG tag start.

target_svg_start = '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF"'
replacement_svg_start = '<svg class="icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#9CA3AF" style="stroke: #9CA3AF !important;"'

base_dir = r"c:\Users\user\Downloads\newuisite\templates"

count = 0
for filename in os.listdir(base_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        if target_svg_start in content and "/platform/profile" in content:
             new_content = content.replace(target_svg_start, replacement_svg_start)
             if new_content != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"Corrected {filename}")
                count += 1
        elif 'style="stroke: #9CA3AF !important;"' not in content and "/platform/profile" in content:
            # Fallback if the previous match failed (maybe whitespace diffs)
            # Try matching just the stroke part if safe
            pass

print(f"Total corrected: {count}")
