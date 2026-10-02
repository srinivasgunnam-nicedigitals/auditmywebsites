import os
import re

templates_dir = 'templates'
files = [f for f in os.listdir(templates_dir) if f.endswith('.html')]

for filename in files:
    path = os.path.join(templates_dir, filename)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
        sidebar_match = re.search(r'<!-- Sidebar -->\s*<aside.*?</aside>', content, re.DOTALL)
        if not sidebar_match:
             sidebar_match = re.search(r'<aside.*?</aside>', content, re.DOTALL)
             
        if sidebar_match:
            sidebar = sidebar_match.group(0)
            # Find all section titles in the sidebar
            titles = re.findall(r'<span>(Audit\s*(?:History|Tools))</span>', sidebar, re.IGNORECASE)
            print(f"{filename}: {titles}")
