#!/usr/bin/env bash
cd /app/share/voiceneves
export PYTHONPATH=/app/lib/python3.12/site-packages:/app/lib/python3/site-packages:$PYTHONPATH
exec python3 softphone.py "$@"
