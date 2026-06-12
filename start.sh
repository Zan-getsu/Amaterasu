<<<<<<< HEAD
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi
python3 update.py && python3 -m bot
=======
#!/bin/bash

python update.py
exec python -m bot
>>>>>>> 8af04aa (feat: add Mega upload/clone support, Drive Categories, and infrastructure improvements)
