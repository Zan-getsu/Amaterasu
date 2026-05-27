import os
filepath = r"m:\Projects\Amaterasu\bot\modules\users_settings.py"
with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for i in range(len(lines)):
    line = lines[i]
    if line.strip() == ')':
        prev_idx = i - 1
        while prev_idx >= 0 and not lines[prev_idx].strip():
            prev_idx -= 1
        if prev_idx >= 0:
            prev = lines[prev_idx].strip()
            if ('data_button(' in prev or 'url_button(' in prev) and prev.endswith(')'):
                # Skip this stray parenthesis
                continue
    new_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
