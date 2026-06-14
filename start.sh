#!/bin/bash

if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

python3 update.py
exec python3 -m bot
