#!/usr/bin/env bash
# Запуск Telegram-бота ARTurokAI. Токен берётся из файла .env (см. .env.example).
set -e
cd "$(dirname "$0")"
[ -d .venv ] && . .venv/bin/activate
python -m arturokai.telegram_bot
