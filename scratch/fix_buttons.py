import os
import re

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original = content

    # Standardize common navigation/action button patterns
    replacements = [
        (r'("|\')✕ Cancel("|\')', r'"✕ CANCEL"'),
        (r'("|\')✕  Close("|\')', r'"✕ CLOSE"'),
        (r'("|\')✕ Close("|\')', r'"✕ CLOSE"'),
        (r'("|\')↩  Back("|\')', r'"↩ BACK"'),
        (r'("|\')↩ Back("|\')', r'"↩ BACK"'),
        (r'("|\')↻  Refresh("|\')', r'"↻ REFRESH"'),
        (r'("|\')↻ Refresh("|\')', r'"↻ REFRESH"'),
        (r'("|\')⚙ Settings("|\')', r'"⚙ SETTINGS"'),
        (r'("|\')⌗ Main Menu("|\')', r'"⌗ MAIN MENU"'),
        (r'("|\')❮  Prev("|\')', r'"❮ PREV"'),
        (r'("|\')Next  ❯("|\')', r'"NEXT ❯"'),
        (r'("|\')❮ Prev("|\')', r'"❮ PREV"'),
        (r'("|\')Next ❯("|\')', r'"NEXT ❯"'),
        (r'("|\')▲ Up("|\')', r'"▲ UP"'),
        (r'("|\')▼ Down("|\')', r'"▼ DOWN"'),
        (r'("|\')Done("|\')', r'"✅ DONE"'),
        (r'("|\')Close("|\')', r'"✕ CLOSE"'),
        (r'("|\')Cancel("|\')', r'"✕ CANCEL"'),
        (r'("|\')Back("|\')', r'"↩ BACK"'),
        (r'("|\')Refresh("|\')', r'"↻ REFRESH"'),
        (r'("|\')Settings("|\')', r'"⚙ SETTINGS"'),
        
        # In case we missed any ❖ variations
        (r'("|\')❖ (.*?)\1', lambda m: f'"{m.group(2).upper()}"' if 'MP3' not in m.group(2) else m.group(0)),
    ]
    
    # We only apply these if it's inside data_button or url_button or similar
    # But doing a global replace for "✕ Cancel" to "✕ CANCEL" is safe in these files.
    for pattern, repl in replacements:
        if callable(repl):
            pass # We'll do it separately or it might be complex. Actually let's just do regexes.
            
    # Safer regex replacements targeting data_button and url_button calls
    # pattern: data_button("Text", ... -> data_button("TEXT", ...
    
    def replacer(match):
        method = match.group(1)
        quote = match.group(2)
        text = match.group(3)
        rest = match.group(4)
        
        # Clean text
        text = text.replace("  ", " ").strip()
        
        # Mappings
        upper_text = text.upper()
        if upper_text == "CANCEL" or upper_text == "✕ CANCEL": text = "✕ CANCEL"
        elif upper_text == "CLOSE" or upper_text == "✕ CLOSE": text = "✕ CLOSE"
        elif upper_text == "BACK" or upper_text == "↩ BACK": text = "↩ BACK"
        elif upper_text == "REFRESH" or upper_text == "↻ REFRESH": text = "↻ REFRESH"
        elif upper_text == "SETTINGS" or upper_text == "⚙ SETTINGS": text = "⚙ SETTINGS"
        elif upper_text == "PREV" or upper_text == "❮ PREV" or upper_text == "❮  PREV": text = "❮ PREV"
        elif upper_text == "NEXT" or upper_text == "NEXT ❯" or upper_text == "NEXT  ❯": text = "NEXT ❯"
        elif upper_text == "UP" or upper_text == "▲ UP": text = "▲ UP"
        elif upper_text == "DOWN" or upper_text == "▼ DOWN": text = "▼ DOWN"
        elif upper_text == "DONE": text = "✅ DONE"
        
        # For things like "❖ Bot", "❖ OS", "❖ MP3"
        elif text.startswith("❖ "):
             # let's keep some or convert if it's menu options
             text = text.upper()
        
        return f'{method}({quote}{text}{quote}{rest}'
        
    content = re.sub(r'(data_button|url_button|InlineKeyboardButton)\(\s*(["\'])(.*?)\2(.*?)\)', replacer, content)

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {filepath}")

for root, _, files in os.walk('m:\\Projects\\Amaterasu'):
    if 'site-packages' in root or '.git' in root:
        continue
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))
