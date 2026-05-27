import re
import os

def rewrite_blocks(content):
    # This regex finds the `text = f"""..."""` blocks
    pattern = re.compile(r'(text = f\"\"\"<b>❖ (.*?) SETTINGS</b>\n)(.*?)(\"\"\")', re.DOTALL)
    
    def replacer(match):
        prefix = match.group(1)
        title = match.group(2)
        body = match.group(3)
        suffix = match.group(4)
        
        lines = body.strip().split('\n')
        new_lines = []
        new_lines.append("<pre>")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if '┄┄┄' in line:
                continue
            
            # Match old style ├ Name       : {user_name}
            # or ├ Leech Type : <code>{ltype}</code>
            # or └ Tele Lang  : ...
            
            m = re.match(r'^[├└]\s*(.*?)\s*:\s*(.*)$', line)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                # we don't know if it's the last line here easily, but we can do it after collecting
                new_lines.append((key, val))
            else:
                new_lines.append(line)
        
        # Now format new_lines
        formatted = ["<pre>"]
        
        # find the longest key
        max_key_len = 0
        for item in new_lines:
            if isinstance(item, tuple):
                max_key_len = max(max_key_len, len(item[0]))
        
        # if max_key_len is less than 11, let's pad to 11 at least, or just max_key_len
        # The prompt says: "All labels within a section must be structurally aligned using exact space padding based on the longest key length."
        # Or I can just use `.ljust(11)` style via f-strings: `f"├─ {key:<{max_key_len}}: {val}"`
        # But wait, since we are inside `f"""..."""`, we can just output literal spaces for the static keys.
        
        for i, item in enumerate(new_lines):
            if item == "<pre>":
                continue
            
            is_last = False
            # Check if this is the last tuple
            if isinstance(item, tuple):
                # check if there are no more tuples after this
                if not any(isinstance(x, tuple) for x in new_lines[i+1:]):
                    is_last = True
                
                key = item[0]
                val = item[1]
                
                # strip out <code></code> from val if it exists, as we are already inside <pre>
                val = re.sub(r'</?code>', '', val)
                
                # padding
                padded_key = key.ljust(max_key_len)
                
                symbol = '└─' if is_last else '├─'
                formatted.append(f"{symbol} {padded_key}: {val}")
            else:
                formatted.append(item)
                
        formatted.append("</pre>")
        
        return prefix + "\n".join(formatted) + "\n" + suffix

    new_content = pattern.sub(replacer, content)
    return new_content

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = rewrite_blocks(content)
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, _, files in os.walk('m:\\Projects\\Amaterasu\\bot\\modules'):
    for file in files:
        if file.endswith('.py'):
            process_file(os.path.join(root, file))

# Fix Private Files specifically
bot_settings = 'm:\\Projects\\Amaterasu\\bot\\modules\\bot_settings.py'
with open(bot_settings, 'r', encoding='utf-8') as f:
    bs = f.read()

# Replace Private Files block
old_private = 'msg = f"""⌬ <b>Private File Settings</b>\\n┠ <b>Dashboard :</b> \\n┃\\n┠ {txt}\\n┃\\n┠ <b>Delete File</b> → Send the file name as text message, Like <code>rclone.conf</code>.\\n┃\\n┖ <b>Note:</b> Changing .netrc will not take effect for aria2c until restart."""'
new_private = 'msg = f"""<b>❖ PRIVATE FILE SETTINGS</b>\\n<pre>\\n├─ ─── DASHBOARD ─────────────────\\n{txt}\\n├─ ─── INSTRUCTIONS ──────────────\\n├─ Delete File : Send file name as text\\n└─ Note        : Changing .netrc requires restart\\n</pre>"""'

if old_private in bs:
    bs = bs.replace(old_private, new_private)
    # Also fix txt generator
    old_txt_gen = 'txt = "\\n┠ ".join(\\n            [\\n                f"<code>{fn}</code> → <b>{\'Exists\' if await aiopath.isfile(fn) else \'Not Exists\'}</b>"\\n                for fn in ['
    new_txt_gen = 'txt = "\\n".join(\\n            [\\n                f"├─ {fn:<15}: {\'Exists\' if await aiopath.isfile(fn) else \'Missing\'}"\\n                for fn in ['
    bs = bs.replace(old_txt_gen, new_txt_gen)
    
    old_edit_mode = 'msg += "\\n\\n<i>Send the file name to delete the file, file to save the file & for new file create, follow below format.</i> \\n\\n<b>Format:</b> \\nfile_name\\n\\ncontents of file</i>\\n\\n<b>Time Left :</b> <code>60 sec</code>"'
    new_edit_mode = 'msg += "\\n<b>FORMAT:</b>\\n<pre>\\nfile_name\\ncontents of file\\n</pre>\\n<b>Time Left :</b> 60 sec"'
    bs = bs.replace(old_edit_mode, new_edit_mode)
    
    with open(bot_settings, 'w', encoding='utf-8') as f:
        f.write(bs)
    print("Updated bot_settings.py Private Settings")
