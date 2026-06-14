lines = open('bot/modules/users_settings.py', 'r', encoding='utf-8').readlines()
quotes = []
for i, line in enumerate(lines):
    if '\"\"\"' in line:
        count = line.count('\"\"\"')
        for _ in range(count):
            quotes.append(i + 1)

print(f"Total quotes: {len(quotes)}")
is_open = False
for q in quotes:
    is_open = not is_open
    state = "OPEN" if is_open else "CLOSE"
    print(f"Line {q}: {state}")

