"""Telegram-бот ARTurokAI: выдаёт покупателям коды и логины, помогает админу.

Запуск:
    export ARTUROKAI_BOT_TOKEN=токен_от_@BotFather
    export ARTUROKAI_ADMINS=123456789,987654321      # ваши Telegram ID (через запятую)
    export ARTUROKAI_SITE=https://ваш-сайт
    python -m arturokai.telegram_bot

Токен и список админов берутся ТОЛЬКО из переменных окружения — в коде их нет.
Работает на «длинных опросах» (long polling), внешний адрес боту не нужен.

Команды покупателя:
  /start, /site — ссылка на сайт и как начать.
Команды администратора (только для ID из ARTUROKAI_ADMINS):
  /plan <тариф> [кол-во]   — выдать коды подписки
  /credits <число> [кол-во] — выдать коды пакета генераций
  /codes                    — последние коды и их статус
  /stats                    — сколько пользователей и активаций
"""
import html
import os
import sys
import time

import requests

from .config import load_config
from .envfile import load_env
from .store import Store, StoreError

API = "https://api.telegram.org/bot{token}/{method}"


def env_admins() -> set[int]:
    raw = os.environ.get("ARTUROKAI_ADMINS", "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().isdigit()}


class Bot:
    def __init__(self, token: str, store: Store, admins: set[int], site: str, plans: dict):
        self.token = token
        self.store = store
        self.admins = admins
        self.site = site
        self.plans = plans
        self.http = requests.Session()

    def call(self, method: str, **params):
        r = self.http.post(API.format(token=self.token, method=method), json=params, timeout=65)
        return r.json()

    def send(self, chat_id: int, text: str):
        self.call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                  disable_web_page_preview=True)

    def run(self):
        print("ARTurokAI Telegram-бот запущен. Остановить — Ctrl+C.")
        offset = None
        while True:
            try:
                resp = self.call("getUpdates", offset=offset, timeout=50)
            except requests.RequestException:
                time.sleep(3)
                continue
            for upd in resp.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if msg and "text" in msg:
                    try:
                        self.handle(msg)
                    except Exception as e:  # один сбой не должен ронять бота
                        self.send(msg["chat"]["id"], f"Ошибка: {html.escape(str(e))}")

    def handle(self, msg: dict):
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        parts = msg["text"].strip().split()
        cmd, args = parts[0].lower().lstrip("/").split("@")[0], parts[1:]

        if cmd in ("start", "help", "site"):
            return self.send(chat_id, self.greeting())
        if cmd == "id":
            return self.send(chat_id, f"Ваш Telegram ID: <code>{user_id}</code>")

        if user_id not in self.admins:
            return self.send(chat_id, "Команда только для администратора. Купить ключ: " + self.greeting())

        if cmd == "plan":
            return self.cmd_plan(chat_id, args)
        if cmd == "credits":
            return self.cmd_credits(chat_id, args)
        if cmd == "codes":
            return self.cmd_codes(chat_id)
        if cmd == "stats":
            return self.cmd_stats(chat_id)
        self.send(chat_id, "Неизвестная команда. /plan, /credits, /codes, /stats")

    def greeting(self) -> str:
        paid = ", ".join(p["name"] for k, p in self.plans.items() if k != "free")
        return (f"<b>ARTurokAI</b> — фото, видео и код.\n\n"
                f"1. Откройте сайт: {self.site}\n"
                f"2. Зарегистрируйтесь (придумайте логин и пароль) — подключится бесплатный тариф.\n"
                f"3. Чтобы открыть платные возможности ({paid}), купите код здесь и активируйте его "
                f"в «Личном кабинете».")

    def cmd_plan(self, chat_id, args):
        if not args:
            plans = " ".join(k for k in self.plans if k != "free")
            return self.send(chat_id, f"Укажите тариф: /plan &lt;{plans}&gt; [кол-во]")
        plan = args[0]
        count = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        codes = self.store.create_codes("plan", count, plan=plan, note="telegram")
        self.send(chat_id, self.codes_block(f"Коды подписки «{self.plans[plan]['name']}»", codes))

    def cmd_credits(self, chat_id, args):
        if not args or not args[0].isdigit():
            return self.send(chat_id, "Укажите кредиты: /credits &lt;число&gt; [кол-во]")
        credits = int(args[0])
        count = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        codes = self.store.create_codes("credits", count, credits=credits, note="telegram")
        self.send(chat_id, self.codes_block(f"Коды на {credits} кредитов", codes))

    def codes_block(self, title: str, codes: list[str]) -> str:
        body = "\n".join(f"<code>{c}</code>" for c in codes)
        return f"<b>{title}</b> ({len(codes)} шт.):\n{body}\n\nОтправьте код покупателю."

    def cmd_codes(self, chat_id):
        rows = self.store.list_codes(limit=15)
        if not rows:
            return self.send(chat_id, "Кодов пока нет.")
        lines = []
        for c in rows:
            what = f"{c['plan']} {c['days']}д" if c["kind"] == "plan" else f"{c['credits']}кр"
            status = f"✅ {c['used_login']}" if c["used_by"] else "🟢 свободен"
            lines.append(f"<code>{c['code']}</code> — {what} — {status}")
        self.send(chat_id, "<b>Последние коды:</b>\n" + "\n".join(lines))

    def cmd_stats(self, chat_id):
        users = self.store.list_users()
        codes = self.store.list_codes(limit=100_000)
        used = sum(1 for c in codes if c["used_by"])
        paid = sum(1 for u in users if u["plan"] != "free")
        self.send(chat_id, f"<b>Статистика</b>\nПользователей: {len(users)} (платных: {paid})\n"
                           f"Кодов: {len(codes)}, активировано: {used}")


def main():
    load_env()                      # читаем токен и ключи из файла .env, если он есть
    token = os.environ.get("ARTUROKAI_BOT_TOKEN")
    if not token:
        sys.exit("Задайте ARTUROKAI_BOT_TOKEN (токен от @BotFather) в переменных окружения.")
    admins = env_admins()
    if not admins:
        print("⚠️ ARTUROKAI_ADMINS не задан — админ-команды будут недоступны. "
              "Узнать свой ID: напишите боту /id.")
    cfg = load_config()
    store = Store(cfg["billing"]["db"], cfg["billing"]["plans"])
    site = os.environ.get("ARTUROKAI_SITE", "http://127.0.0.1:7860")
    Bot(token, store, admins, site, cfg["billing"]["plans"]).run()


if __name__ == "__main__":
    main()
