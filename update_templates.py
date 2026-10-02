import os
import re

TEMPLATE_DIR = 'templates'
CSS_VERSION = '2.47'
JS_VERSION = '2.21'

PRELOAD_SCRIPT = """    <script>
        // Prevent FOUC by applying collapsed state before DOM renders
        if (localStorage.getItem('sidebarCollapsed') === 'true') {
            document.documentElement.classList.add('sidebar-collapsed-preload');
        }
    </script>"""

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove all existing Preload Scripts (to clean up duplicates)
    # The regex looks for <script> blocks containing the sidebarCollapsed logic
    pattern = re.compile(r'\s*<script>\s*// Prevent FOUC.*?sidebar-collapsed-preload.*?<\/script>', re.DOTALL)
    cleaned_content = re.sub(pattern, '', content)
    
    modified = False
    
    # 2. Update CSS Version
    new_content, count = re.subn(r'styles\.css\?v=[0-9.]+', f'styles.css?v={CSS_VERSION}', cleaned_content)
    if count > 0:
        cleaned_content = new_content

    # 3. Update JS Version
    new_content, count = re.subn(r'main\.js\?v=[0-9.]+', f'main.js?v={JS_VERSION}', cleaned_content)
    if count > 0:
        cleaned_content = new_content

    # 4. Inject Preload Script Exactly Once after <head>
    if '<head>' in cleaned_content:
        final_content = cleaned_content.replace('<head>', f'<head>\n{PRELOAD_SCRIPT}', 1)
    elif '<meta charset=' in cleaned_content: # Fallback
        final_content = cleaned_content.replace('<meta charset=', f'{PRELOAD_SCRIPT}\n    <meta charset=', 1)
    else:
        final_content = cleaned_content

    # We always write to ensure it's clean
    if content != final_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(final_content)
        print(f"Updated: {filepath}")

for root, _, files in os.walk(TEMPLATE_DIR):
    for file in files:
        if file.endswith('.html'):
            process_file(os.path.join(root, file))

print("Cleanup and update complete.")
