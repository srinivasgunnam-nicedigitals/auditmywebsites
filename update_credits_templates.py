import os
import re

templates_dir = r"c:\Users\user\Downloads\sitesterpro-main_2 (1)\sitesterpro-main_2\templates"

# Replacement target
target_str = '<a href="#" onclick="showLogoutModal(event)" class="logout-btn-header"'

# New code to prepend
replacement_str = """
            {% if user %}
            <div class="credits-display-header" style="margin-right: 1.5rem; display: flex; align-items: center; gap: 0.5rem; background: rgba(79, 124, 255, 0.1); padding: 0.4rem 0.8rem; border-radius: 8px; border: 1px solid rgba(79, 124, 255, 0.2);">
                <span style="color: #64748B; font-size: 0.65rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Credits</span>
                <span style="color: #4F7CFF; font-weight: 700; font-size: 0.95rem;">{{ user.credits }}</span>
            </div>
            {% endif %}
            <a href="#" onclick="showLogoutModal(event)" class="logout-btn-header\""""

def update_templates():
    updated_files = []
    for filename in os.listdir(templates_dir):
        if filename.endswith(".html") and filename not in ['landing.html']: # Skip landing if already done or different
            filepath = os.path.join(templates_dir, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if target_str in content and '{% if user %}' not in content.split(target_str)[0][-500:]:
                # Only replace if not already replaced nearby
                new_content = content.replace(target_str, replacement_str)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                updated_files.append(filename)
                
    return updated_files

if __name__ == "__main__":
    updated = update_templates()
    print(f"Updated {len(updated)} files: {', '.join(updated)}")
