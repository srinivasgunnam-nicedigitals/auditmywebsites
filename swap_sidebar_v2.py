import os
import re

templates_dir = r'c:\Users\user\Downloads\sitesterpro-main\templates'

# Even more flexible patterns to match the blocks
# We'll match <div class="nav-section-title collapsible followed by any classes
history_block_pattern = re.compile(
    r'(<div class="nav-section-title collapsible[^"]*">\s*<div class="nav-section-main"><img src="/static/svg/audit-history.svg".*?</div>\s*<div class="nav-submenu[^"]*">.*?</div>)',
    re.DOTALL
)

tools_block_pattern = re.compile(
    r'(<div class="nav-section-title collapsible[^"]*">\s*<div class="nav-section-main"><img src="/static/svg/projects-logo.svg".*?</div>\s*<div class="nav-submenu[^"]*">.*?</div>)',
    re.DOTALL
)

count = 0
for root, dirs, files in os.walk(templates_dir):
    for filename in files:
        if filename.endswith('.html'):
            path = os.path.join(root, filename)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Find history block
                history_match = history_block_pattern.search(content)
                # Find tools block
                tools_match = tools_block_pattern.search(content)

                if history_match and tools_match:
                    history_block = history_match.group(1)
                    tools_block = tools_match.group(1)

                    # Find if history is before tools
                    if history_match.start() < tools_match.start():
                        # History is before tools
                        # We need to preserve the content between them
                        between_content = content[history_match.end():tools_match.start()]
                        
                        new_content = (
                            content[:history_match.start()] +
                            tools_block +
                            between_content +
                            history_block +
                            content[tools_match.end():]
                        )
                        
                        with open(path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        print(f"Swapped sections in {filename}")
                        count += 1
                    else:
                        print(f"Sections already swapped or in reverse order in {filename}")
            except Exception as e:
                print(f"Error processing {path}: {e}")

print(f"Total files updated/verified: {count}")
