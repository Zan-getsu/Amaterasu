import os
import re

def fix_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except:
        return
        
    changed = False
    for i, line in enumerate(lines):
        if re.search(r'(data_button|url_button|InlineKeyboardButton)\(', line):
            # If there's more '(' than ')', we likely broke it
            if line.count('(') > line.count(')'):
                stripped = line.rstrip('\n')
                
                # We need to add ')' at the end of the logical statement
                # If it ends with ',', add before it
                if stripped.endswith(','):
                    stripped = stripped[:-1] + '),'
                else:
                    stripped = stripped + ')'
                    
                lines[i] = stripped + '\n'
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
