import os
import re

def check_file(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            h_match = re.search(r'Audit\s*History', content, re.IGNORECASE)
            t_match = re.search(r'Audit\s*Tools', content, re.IGNORECASE)
            
            if h_match and t_match:
                if h_match.start() < t_match.start():
                    # Check if they are actually in the sidebar
                    # A simplistic check: the gap shouldn't be too large and they should be in <span> or labels
                    if t_match.start() - h_match.start() < 5000:
                        print(f"HISTORY_BEFORE_TOOLS in {path} (Pos H: {h_match.start()}, T: {t_match.start()})")
                        context = content[max(0, h_match.start()-100):min(len(content), t_match.end()+100)]
                        print(f"Context: {context}")
                        print("-" * 50)
    except:
        pass

for root, dirs, files in os.walk('.'):
    if any(d in root for d in ['venv', '.git', 'node_modules', '.next']):
        continue
    for f in files:
        if f.endswith(('.html', '.js', '.py')):
            if f in ['strict_check.py', 'final_check.py', 'report_order.py', 'proximity_check.py', 'final_audit_check.py']:
                continue
            check_file(os.path.join(root, f))
