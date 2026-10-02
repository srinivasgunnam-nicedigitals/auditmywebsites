import os
import re

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'
missed_files = []

# More relaxed patterns to find the labels
history_label = re.compile(r'Audit\s+History', re.IGNORECASE)
tools_label = re.compile(r'Audit\s+Tools', re.IGNORECASE)

for root, dirs, files in os.walk(templates_dir):
    for filename in files:
        if filename.endswith('.html'):
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    if history_label.search(content) and tools_label.search(content):
                        # Find the positions
                        h_pos = history_label.search(content).start()
                        t_pos = tools_label.search(content).start()
                        
                        if h_pos < t_pos:
                            missed_files.append(filename)
            except Exception as e:
                print(f"Error reading {path}: {e}")

print("FILES_FOUND_START")
for f in missed_files:
    print(f)
print("FILES_FOUND_END")
