import os
import re

def fix_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except:
        return

    orig = content
    # Fix multiline data_button and url_button
    content = re.sub(r'(data_button|url_button)\(\)\r?\n', r'\1(\n', content)
    
    # Fix InlineKeyboardButton bracket mismatches
    content = content.replace('"]])', '")]]')
    content = content.replace('"]))', '")])')
    content = content.replace('"])]', '")]]')
    content = content.replace('"]),', '")],')
    content = content.replace('"])', '")])')
    
    if orig != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Fixed {filepath}")
            
for root, _, files in os.walk('m:\\Projects\\Amaterasu\\bot'):
    for file in files:
        if file.endswith('.py'):
            fix_file(os.path.join(root, file))
