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
                    # We'll look for the text within the spans
                    sections = re.findall(r'<span>Audit\s*(History|Tools)</span>', content, re.IGNORECASE | re.DOTALL)
                    
                    if sections:
                        print(f"{filename}: {sections}")
            except Exception as e:
                pass
