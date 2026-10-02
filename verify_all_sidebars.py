import os
import re

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'

for root, dirs, files in os.walk(templates_dir):
    for filename in files:
        if filename.endswith('.html'):
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    # Find all section titles in the sidebar
                    sidebar_match = re.search(r'<aside.*?</aside>', content, re.DOTALL)
                    if sidebar_match:
                        sidebar = sidebar_match.group(0)
                        titles = re.findall(r'<span>Audit\s*(History|Tools)</span>', sidebar, re.IGNORECASE | re.DOTALL)
                        if titles:
                            print(f"{filename}: {titles}")
            except Exception as e:
                print(f"Error reading {path}: {e}")
