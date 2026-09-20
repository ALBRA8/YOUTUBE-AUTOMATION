#!/usr/bin/env bash
# Arranque rápido — Linux/Mac
cd "$(dirname "$0")/backend"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
echo "🎬 YT Automation v2.0 → http://127.0.0.1:8000"
uvicorn main:app --host 127.0.0.1 --port 8000
