import os
import glob
import re

template_dir = r"c:/Users/user/Documents/sitesterpro-main/templates"
html_files = glob.glob(os.path.join(template_dir, "*.html"))

# 1. First, remove the back button from the brand div where we just mistakenly added it
# The added back button:
# <a href="javascript:history.back()" class="back-btn" title="Go Back" style="...">
#     <svg ...></svg>
# </a>

back_btn_regex = re.compile(r'\s*<a href="javascript:history\.back\(\)" class="back-btn"[^>]*>.*?</a>', re.DOTALL)

for filepath in html_files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        continue
    
    # Remove the back button we just added
    new_content, count = back_btn_regex.subn('', content)
    
    # Also revert the brand flex styles if they were added
    brand_regex = re.compile(r'<div class="brand" style="display: flex; align-items: center; gap: 0\.5rem;">')
    new_content = brand_regex.sub('<div class="brand">', new_content)
    
    brand_style_regex = re.compile(r'(<div class="brand"[^>]*?)\s*style="display: flex; align-items: center; gap: 0\.5rem;\s*([^"]*)?"')
    def revert_brand_style(match):
        pre = match.group(1)
        rest_style = match.group(2)
        if rest_style:
            return f'{pre} style="{rest_style}"'
        return pre
    
    new_content = brand_style_regex.sub(revert_brand_style, new_content)
    
    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Reverted brand in {os.path.basename(filepath)}")

# 2. Now add the back button to the top left of the main content area.
# Looking at the HTML:
# <div class="page-title">
#     <h1>...</h1>
# </div>
# We can just change <div class="page-title"> to have flex layout and insert the back button before the h1.

page_title_regex = re.compile(r'(<div\s+class="page-title"[^>]*>)\s*(<h[1-6][^>]*>)', re.IGNORECASE)

replaced_count = 0
for filepath in html_files:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        continue
    
    if '<div class="page-title"' in content or '<div class=\"page-title\"' in content:
        def add_back_btn_repl(match):
            div_start = match.group(1)
            h_tag = match.group(2)
            
            # Make sure page-title has flex layout so the button and text align horizontally
            if 'style=' in div_start:
                if 'display: flex' not in div_start:
                    div_start = div_start.replace('style="', 'style="display: flex; align-items: center; gap: 1rem; ')
            else:
                div_start = div_start.replace('class="page-title"', 'class="page-title" style="display: flex; align-items: center; gap: 1rem;"')
            
            back_btn = '''            <a href="javascript:history.back()" class="back-btn" title="Go Back" style="display: flex; align-items: center; justify-content: center; color: var(--text-secondary, #64748B); background: rgba(30, 41, 59, 0.3); border: 1px solid rgba(255, 255, 255, 0.05); text-decoration: none; width: 36px; height: 36px; border-radius: 8px; transition: all 0.2s;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>
            </a>'''
            
            # Add margin 0 to h-tag so it aligns nicely with the button
            if 'style=' in h_tag:
                new_h = h_tag.replace('style="', 'style="margin: 0; ')
            else:
                new_h = h_tag.replace('>', ' style="margin: 0;">')
            
            return f'{div_start}\n{back_btn}\n            {new_h}'
            
        new_content, count = page_title_regex.subn(add_back_btn_repl, content)
        if count > 0:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            replaced_count += count
            print(f"Added back button to main content in {os.path.basename(filepath)}")

print(f"Total files updated with new back button position: {replaced_count}")
