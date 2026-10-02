import os
import re

for root, dirs, files in os.walk('.'):
    if 'venv' in root or '.git' in root:
        continue
    for filename in files:
        if filename.endswith('.html'):
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    matches = list(re.finditer(r'Audit\s*History.*?Audit\s*Tools', content, re.DOTALL | re.IGNORECASE))
                    for m in matches:
                        if len(m.group(0)) < 1500: # Sidebar sections are usually close
                            print(f"FOUND MISMATCH in {path} at position {m.start()}")
                            # Print a snippet
                            print(f"Snippet: {content[max(0, m.start()-50):min(len(content), m.end()+50)]}")
                            print("-" * 40)
            except Exception as e:
                pass
