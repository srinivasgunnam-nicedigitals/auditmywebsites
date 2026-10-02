import os
import glob
import re

template_dir = r"C:\Users\user\Documents\sitesterpro-main\templates"
files = glob.glob(os.path.join(template_dir, "*.html"))

fixed_count = 0

pattern = re.compile(
    r'(<a\s+href="[^"]*"\s+class="view-report-btn"[^>]*>.*?</a>\s*</div>)(\s*<!-- Custom Confirmation Modal -->\s*<div id="confirm-modal" class="modal-overlay" style="display: none;">\s*<div class="modal-content" style="max-width: 400px;">.*?<div class="modal-footer"[^>]*>.*?</div>\s*</div>\s*</div>)(\s*</div>)',
    re.DOTALL
)

for filepath in files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Try the replacement
    new_content, count = pattern.subn(r'\1\n    </div>\2', content)
    
    if count > 0:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed {filepath}")
        fixed_count += count

print(f"Total files fixed: {fixed_count}")
