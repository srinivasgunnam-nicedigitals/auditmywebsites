
import os

file_path = r"c:\Users\user\Documents\newuisite - Copy\main.py"

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
in_dedent_block = False
dedent_start_marker = "# 2. Optimized Hybrid Scroll (Lazy Load Trigger)"
dedent_end_marker = "— DONE\")" # Part of print line

# We also need to handle the orphaned except block
orphaned_except_marker = "print(f\"[STATIC][{browser_name}] FAILED {url}"

# Adjust state based on markers
for i, line in enumerate(lines):
    # Check for start of block to dedent
    if dedent_start_marker in line:
        in_dedent_block = True
    
    if in_dedent_block:
        # Dedent by 4 spaces (from 20 to 16)
        if line.startswith("                    "):
            new_lines.append(line.replace("                    ", "                ", 1))
        else:
            # If line is empty or has less indentation but is in block?
            # Just keep as is if it's blank, but check for end of block
            if line.strip() == "":
                new_lines.append(line)
            else:
                 # Should not happen if strictly indented, but fallback
                new_lines.append(line)
    else:
        # Handle the orphaned except block
        # We look for the except Exception as e that is followed by the specific error print
        # This is heuristics.
        # Actually, simpler: finding the specific except block at the end of process_url
        # line ~697
        if "except Exception as e:" in line and i < len(lines)-1 and orphaned_except_marker in lines[i+1]:
             new_lines.append("# " + line) # Comment out except
        elif orphaned_except_marker in line:
             new_lines.append("# " + line) # Comment out print
        else:
            new_lines.append(line)
            
    # Check for end of block (after appending)
    if in_dedent_block and dedent_end_marker in line:
        in_dedent_block = False

with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Fixed indentation in main.py")
