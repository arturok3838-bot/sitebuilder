#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  . .venv/bin/activate
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
  pip install -r requirements.txt
else
  . .venv/bin/activate
fi
python -m arturokai.server "$@"
