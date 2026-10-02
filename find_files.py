import os
import re

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'
files_to_edit = []

# Pattern to match "Audit" followed by "History" or "Tools" with possible whitespace/newline in between
history_pattern = re.compile(r'Audit\s+History', re.IGNORECASE | re.DOTALL)
tools_pattern = re.compile(r'Audit\s+Tools', re.IGNORECASE | re.DOTALL)

for filename in os.listdir(templates_dir):
    if filename.endswith('.html'):
        path = os.path.join(templates_dir, filename)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                if history_pattern.search(content) and tools_pattern.search(content):
                    files_to_edit.append(path)
        except Exception as e:
            print(f"Error reading {path}: {e}")

for file in files_to_edit:
    print(file)
