import os

audit_tools_anchor = '<span>Compare Meta Tags</span>\n            </a>'
audit_tools_anchor_rn = '<span>Compare Meta Tags</span>\r\n            </a>'

history_anchor = '<span>Compare Meta Tags</span>\n            </a>'
history_anchor_rn = '<span>Compare Meta Tags</span>\r\n            </a>'

audit_image_alt = """
            <a href="/platform/image-alt" class="nav-item">
                <img src="/static/svg/accessibility.svg" class="icon" alt="">
                <span>Image Alt Attributes</span>
            </a>"""

history_image_alt = """
            <a href="/platform/history?type=image-alt" class="nav-item">
                <img src="/static/svg/accessibility.svg" class="icon" alt="">
                <span>Image Alt Attributes</span>
            </a>"""

base_dir = r"c:\Users\user\Documents\sitesterpro-main\templates"
updated_count = 0

for filename in os.listdir(base_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        if "Image Alt Attributes" not in content:
            # Audit Tools section (first occurrence usually)
            
            # We can use split and join or find
            # Find the index of the first `href="/scan/meta-tags"`
            idx1 = content.find('href="/scan/meta-tags"')
            if idx1 != -1:
                # Find the end of the </a> tag after this
                end_a1 = content.find('</a>', idx1)
                if end_a1 != -1:
                    content = content[:end_a1 + 4] + audit_image_alt + content[end_a1 + 4:]
            
            # Find the index of the `href="/platform/history?type=meta-tags"`
            idx2 = content.find('href="/platform/history?type=meta-tags"')
            if idx2 != -1:
                end_a2 = content.find('</a>', idx2)
                if end_a2 != -1:
                    content = content[:end_a2 + 4] + history_image_alt + content[end_a2 + 4:]
            
            if "Image Alt Attributes" in content:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Updated {filename}")
                updated_count += 1
            else:
                print(f"Could not update {filename}")

print(f"Total files updated: {updated_count}")
