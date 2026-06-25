#!/bin/bash

if [ -d "/amaterasuvenv" ]; then
    source /amaterasuvenv/bin/activate
elif [ -d "/wzvenv" ]; then
    source /wzvenv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# ── Sanitise config.py encoding (permanent fix for non-UTF-8 files) ──
# If the user saved config.py with a Windows editor (CP1252/Latin-1),
# Python 3 will refuse to parse it.  Detect and auto-convert to UTF-8
# on every boot so the error never surfaces.
if [ -f "config.py" ]; then
    if ! python3 -c "open('config.py', encoding='utf-8').read()" 2>/dev/null; then
        echo "[startup] config.py contains non-UTF-8 bytes — converting to UTF-8 ..."
        if command -v iconv >/dev/null 2>&1; then
            iconv -f WINDOWS-1252 -t UTF-8 config.py -o config.py.utf8 \
                && mv config.py.utf8 config.py \
                && echo "[startup] config.py converted successfully."
        else
            # Fallback: use Python's own codec machinery
            python3 -c "
import pathlib, sys
p = pathlib.Path('config.py')
try:
    raw = p.read_bytes()
    text = raw.decode('utf-8-sig')       # already UTF-8 with BOM?
except UnicodeDecodeError:
    text = raw.decode('cp1252')          # assume Windows-1252
p.write_text(text, encoding='utf-8')
print('[startup] config.py converted to UTF-8 via Python fallback.')
"
        fi
    fi
fi

python3 update.py
exec python3 -m bot
