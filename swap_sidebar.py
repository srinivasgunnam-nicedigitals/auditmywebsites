import os
import re

def swap_sidebar_sections(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define regex patterns for the two blocks
    # Block A: Audit History
    # Block B: Audit Tools
    
    # Pattern for History block (title + submenu)
    history_pattern = r'(<div class="nav-section-title collapsible.*?>\s*<div class="nav-section-main"><img src="/static/svg/audit-history\.svg".*?</div>\s*<svg class="submenu-toggle".*?>.*?</svg>\s*</div>\s*<div class="nav-submenu.*?>.*?</div>)'
    
    # Pattern for Tools block (title + submenu)
    tools_pattern = r'(<div class="nav-section-title collapsible.*?>\s*<div class="nav-section-main"><img src="/static/svg/projects-logo\.svg".*?</div>\s*<svg class="submenu-toggle".*?>.*?</svg>\s*</div>\s*<div class="nav-submenu.*?>.*?</div>)'

    # Find them
    history_match = re.search(history_pattern, content, re.DOTALL)
    tools_match = re.search(tools_pattern, content, re.DOTALL)

    if history_match and tools_match:
        # Check if History is before Tools
        if history_match.start() < tools_match.start():
            print(f"Swapping sections in {file_path}")
            
            # Extract the blocks
            history_block = history_match.group(1)
            tools_block = tools_match.group(1)
            
            # The gaps between and around blocks might be important, but usually it's just whitespace in sidebars.
            # We want to replace Block A with Block B and Block B with Block A.
            
            # Safer way: Find the range from the start of first block to end of second block
            start = history_match.start()
            end = tools_match.end()
            
            # Content between blocks
            mid = content[history_match.end():tools_match.start()]
            
            new_sidebar_part = tools_block + mid + history_block
            
            new_content = content[:start] + new_sidebar_part + content[end:]
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            return True
    return False

templates_dir = r"c:\Users\user\Downloads\sitesterpro-main\templates"
files_to_fix = [
    "accessibility_audit.html", "accessibility_detail.html", "accessibility_report.html", 
    "audit_history.html", "device_lab.html", "h1_report.html", "h1_tags.html", 
    "keyword_rank.html", "metatags.html", "meta_report.html", "performance_audit.html", 
    "performance_report.html", "phone_report.html", "phone_validator.html", "profile.html", 
    "sitemaps.html", "sitemap_report.html", "static.html", "static_report.html", "static_snapshots.html"
]

for filename in files_to_fix:
    path = os.path.join(templates_dir, filename)
    if os.path.exists(path):
        swap_sidebar_sections(path)
    else:
        print(f"Skipping {filename} - does not exist")
