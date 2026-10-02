import os
import re

# We want to find the Meta Tags link in Audit Tools section and insert Image Alt after it.
# Meta Tags link block looks like:
#             <a href="/scan/meta-tags" class="nav-item">
#                 <img src="/static/svg/metatags.svg" class="icon" alt="">
#                 <span>Compare Meta Tags</span>
#             </a>

audit_tools_meta_pattern = re.compile(
    r'(<a href="/scan/meta-tags" class="nav-item(?: active)?">\s*<img src="/static/svg/metatags\.svg" class="icon" alt="">\s*<span>Compare Meta Tags</span>\s*</a>)',
    re.MULTILINE | re.IGNORECASE
)

audit_tools_image_alt = """\\1
            <a href="/platform/image-alt" class="nav-item">
                <img src="/static/svg/accessibility.svg" class="icon" alt="">
                <span>Image Alt Attributes</span>
            </a>"""

# Audit History meta tags block:
#             <a href="/platform/history\?type=meta-tags" class="nav-item(?: active)?">
#                 <img src="/static/svg/metatags.svg" class="icon" alt="">
#                 <span>Compare Meta Tags</span>
#             </a>
history_meta_pattern = re.compile(
    r'(<a href="/platform/history\?type=meta-tags" class="nav-item(?: active)?">\s*<img src="/static/svg/metatags\.svg" class="icon" alt="">\s*<span>Compare Meta Tags</span>\s*</a>)',
    re.MULTILINE | re.IGNORECASE
)

history_image_alt = """\\1
            <a href="/platform/history?type=image-alt" class="nav-item">
                <img src="/static/svg/accessibility.svg" class="icon" alt="">
                <span>Image Alt Attributes</span>
            </a>"""

# Special handling for already having active in Image Alt template if needed,
# but the user didn't mention it. If it's already there, we check "Image Alt Attributes".

base_dir = r"c:\Users\user\Documents\sitesterpro-main\templates"
updated_count = 0

for filename in os.listdir(base_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if "Image Alt Attributes" not in content:
            # Missing from this template.
            # Replace in Audit Tools
            new_content = audit_tools_meta_pattern.sub(audit_tools_image_alt, content)
            
            # Replace in Audit History
            new_content = history_meta_pattern.sub(history_image_alt, new_content)
            
            if new_content != content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"Updated {filename}")
                updated_count += 1
            else:
                print(f"Could not find pattern in {filename}")

print(f"Total files updated: {updated_count}")
