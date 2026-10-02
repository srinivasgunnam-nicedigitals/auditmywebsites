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
                    
                    # Look for "Audit" followed by "History" then "Audit" followed by "Tools"
                    # We'll search for them within the same string but allow any characters between
                    # This is very loose to catch split lines
                    
                    history_match = re.search(r'Audit\s+History', content, re.IGNORECASE | re.DOTALL)
                    tools_match = re.search(r'Audit\s+Tools', content, re.IGNORECASE | re.DOTALL)
                    
                    if history_match and tools_match:
                        # Find the first occurrences of each specifically for the sidebar
                        # We'll search for several versions of the label to be sure
                        
                        labels = []
                        # Find all occurrences of Audit History and Audit Tools
                        for m in re.finditer(r'Audit\s*(History|Tools)', content, re.IGNORECASE | re.DOTALL):
                            labels.append((m.start(), m.group(1).capitalize()))
                        
                        # Filter labels to only include those that are PLUS something else in the sidebar
                        # Actually, let's just print all labels and their order for each file
                        print(f"FILE: {filename}")
                        for pos, label in labels:
                            print(f"  {pos}: {label}")
                            
            except Exception as e:
                pass
