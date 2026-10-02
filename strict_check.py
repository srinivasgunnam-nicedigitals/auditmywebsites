import os

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'

for root, dirs, files in os.walk(templates_dir):
    for filename in files:
        if filename.endswith('.html'):
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    # Search for the sidebar labels specifically in the collapsible headers
                    # We look for the literal text "Tools" and "History" in the spans
                    
                    history_idx = content.find('<span>Audit\n                    History</span>')
                    if history_idx == -1:
                         history_idx = content.find('<span>Audit\nHistory</span>')
                    if history_idx == -1:
                        history_idx = content.find('<span>Audit History</span>')
                    if history_idx == -1:
                         history_idx = content.find('History</span>')

                    tools_idx = content.find('<span>Audit\n                    Tools</span>')
                    if tools_idx == -1:
                        tools_idx = content.find('<span>Audit\nTools</span>')
                    if tools_idx == -1:
                        tools_idx = content.find('<span>Audit Tools</span>')
                    if tools_idx == -1:
                        tools_idx = content.find('Tools</span>')

                    if history_idx != -1 and tools_idx != -1:
                        if history_idx < tools_idx:
                            # Double check it's in the sidebar
                            sidebar_start = content.find('<aside')
                            sidebar_end = content.find('</aside>')
                            if sidebar_start != -1 and sidebar_end != -1:
                                if sidebar_start < history_idx < sidebar_end and sidebar_start < tools_idx < sidebar_end:
                                    print(f"WRONG_ORDER: {filename}")
            except Exception as e:
                pass
