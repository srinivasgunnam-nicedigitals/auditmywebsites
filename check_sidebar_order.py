import os
import re

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'

# Find the icons instead of labels, as they are more consistent and usually on one line
history_icon = '/static/svg/audit-history.svg'
tools_icon = '/static/svg/projects-logo.svg'

for root, dirs, files in os.walk(templates_dir):
    for filename in files:
        if filename.endswith('.html'):
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    if history_icon in content and tools_icon in content:
                        h_pos = content.find(history_icon)
                        t_pos = content.find(tools_icon)
                        
                        order = "OK (Tools first)" if t_pos < h_pos else "WRONG (History first)"
                        print(f"{filename}: {order}")
                    elif history_icon in content:
                        print(f"{filename}: Only History found")
                    elif tools_icon in content:
                        print(f"{filename}: Only Tools found")
            except Exception as e:
                print(f"Error reading {path}: {e}")
