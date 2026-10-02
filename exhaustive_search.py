import os
import re

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'

# icons
history_icon = '/static/svg/audit-history.svg'
tools_icon = '/static/svg/projects-logo.svg'

results = []

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
                        
                        if h_pos < t_pos:
                            results.append(filename)
            except Exception as e:
                print(f"Error reading {path}: {e}")

print("INCORRECT_ORDER_START")
for r in results:
    print(r)
print("INCORRECT_ORDER_END")
