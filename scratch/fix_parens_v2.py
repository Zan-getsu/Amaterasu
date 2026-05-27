import os
import re

def fix_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        return
        
    changed = False
    for i, line in enumerate(lines):
        if re.search(r'(data_button|url_button|InlineKeyboardButton)\(', line):
            # Only process if there's a missing closing parenthesis on this line
            if line.count('(') - line.count(')') == 1:
                # To prevent breaking multiline calls (like `buttons.data_button(\n`),
                # ensure the line actually has arguments (contains quotes) and isn't just an open parenthesis.
                if '"' in line or "'" in line:
                    # Find trailing whitespace, commas, or brackets
                    m = re.search(r'([\]\s,]*)$', line)
                    trailing = m.group(1) if m else ''
                    core = line[:len(line)-len(trailing)]
                    
                    lines[i] = core + ')' + trailing
                    changed = True
                    
    if changed:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.writelines(lines)
            
for root, _, files in os.walk('m:\\Projects\\Amaterasu\\bot'):
    for file in files:
        if file.endswith('.py'):
            fix_file(os.path.join(root, file))
            
for root, _, files in os.walk('m:\\Projects\\Amaterasu\\plugins'):
    for file in files:
        if file.endswith('.py'):
            fix_file(os.path.join(root, file))
