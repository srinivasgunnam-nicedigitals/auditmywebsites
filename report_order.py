import os
import re

templates_dir = 'templates'
files = [f for f in os.listdir(templates_dir) if f.endswith('.html')]

for filename in files:
    path = os.path.join(templates_dir, filename)
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
        # Look for the first occurrence of History and Tools in the sidebar
        sidebar_match = re.search(r'<aside.*?</aside>', content, re.DOTALL)
        if sidebar_match:
            sidebar = sidebar_match.group(0)
            history_pos = sidebar.find('History')
            tools_pos = sidebar.find('Tools')
            
            if history_pos != -1 and tools_pos != -1:
                if history_pos < tools_pos:
                    print(f"WRONG: {filename}")
                else:
                    print(f"OK: {filename}")
            elif history_pos != -1:
                print(f"ONLY_HISTORY: {filename}")
            elif tools_pos != -1:
                print(f"ONLY_TOOLS: {filename}")
            else:
                print(f"NO_LABELS: {filename}")
