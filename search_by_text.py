import os
import re

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'

results = []

for root, dirs, files in os.walk(templates_dir):
    for filename in files:
        if filename.endswith('.html'):
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    # Find the sidebar content
                    sidebar_match = re.search(r'<aside.*?</aside>', content, re.DOTALL)
                    if sidebar_match:
                        sidebar = sidebar_match.group(0)
                        
                        # Find if it has History and Tools
                        if 'History' in sidebar and 'Tools' in sidebar:
                            h_pos = sidebar.find('History')
                            t_pos = sidebar.find('Tools')
                            
                            if h_pos < t_pos:
                                results.append(filename)
            except Exception as e:
                print(f"Error reading {path}: {e}")

print("FILES_WITH_HISTORY_FIRST_START")
for r in results:
    print(r)
print("FILES_WITH_HISTORY_FIRST_END")
