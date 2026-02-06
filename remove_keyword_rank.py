import os
import re

# Define the pattern for the Keyword Rank link block
# We use a regex that matches the structure we added
pattern = re.compile(r'\s*<a href="/scan/keyword-rank" class="nav-item.*?">.*?Keyword Rank\s*</span>\s*</a>', re.DOTALL | re.IGNORECASE)

# Target directory
templates_dir = r"c:\Users\user\Downloads\newuisite - Copy\templates"

def remove_keyword_rank(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if the file contains the pattern
        if not pattern.search(content):
            return False
            
        # Replace with empty string
        new_content = pattern.sub('', content)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False

count = 0
for root, dirs, files in os.walk(templates_dir):
    for file in files:
        if file.endswith(".html"):
            full_path = os.path.join(root, file)
            if remove_keyword_rank(full_path):
                print(f"Removed from: {file}")
                count += 1

print(f"Done. Removed from {count} files.")
