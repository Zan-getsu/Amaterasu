#!/bin/bash

if [ -d "/amaterasuvenv" ]; then
    source /amaterasuvenv/bin/activate
elif [ -d "/wzvenv" ]; then
    source /wzvenv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python3 update.py
exec python3 -m bot
