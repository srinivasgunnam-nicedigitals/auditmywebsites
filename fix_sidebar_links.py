
import os
import re

TEMPLATES_DIR = r"c:\Users\user\Downloads\ab - Copy\templates"

def fix_files():
    count = 0
    for root, dirs, files in os.walk(TEMPLATES_DIR):
        for file in files:
            if file.endswith(".html"):
                filepath = os.path.join(root, file)
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Regex to find the Dashboard link
                # Looking for <a href="#" class="nav-item"> (or dashboard.html)
                # followed immediately by the dashboard logo image
                
                # Pattern 1: href="#"
                pattern1 = r'(<a\s+href=["\']#["\']\s+class=["\']nav-item(?: active)?["\']>\s*<img\s+src=["\']/static/svg/dashboard-logo\.svg["\'])'
                
                # Pattern 2: href="dashboard.html"
                pattern2 = r'(<a\s+href=["\']dashboard\.html["\']\s+class=["\']nav-item(?: active)?["\']>\s*<img\s+src=["\']/static/svg/dashboard-logo\.svg["\'])'

                # Pattern 3: href="/" (just in case)
                pattern3 = r'(<a\s+href=["\']/["\']\s+class=["\']nav-item(?: active)?["\']>\s*<img\s+src=["\']/static/svg/dashboard-logo\.svg["\'])'

                new_content = content
                
                # Replacement function
                def replace_dash(match):
                    # Replace href="#" or href="dashboard.html" with href="/platform/dashboard"
                    # We reconstruct the tag. We need to preserve "class" (active or not)
                    original = match.group(1)
                    if 'href="#"' in original:
                        return original.replace('href="#"', 'href="/platform/dashboard"')
                    elif "href='#'" in original:
                        return original.replace("href='#'", 'href="/platform/dashboard"')
                    elif 'href="dashboard.html"' in original:
                        return original.replace('href="dashboard.html"', 'href="/platform/dashboard"')
                    elif 'href="/"' in original:
                        return original.replace('href="/"', 'href="/platform/dashboard"')
                    return original

                new_content = re.sub(pattern1, replace_dash, new_content)
                new_content = re.sub(pattern2, replace_dash, new_content)
                new_content = re.sub(pattern3, replace_dash, new_content)

                if new_content != content:
                    print(f"Fixing {file}...")
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    count += 1
    
    print(f"Total files fixed: {count}")

if __name__ == "__main__":
    fix_files()
