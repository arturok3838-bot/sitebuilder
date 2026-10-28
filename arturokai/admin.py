"""Управление ARTurokAI из терминала.

  python -m arturokai.admin create-admin ЛОГИН             — создать администратора
  python -m arturokai.admin codes --plan start --count 10  — коды подписки
  python -m arturokai.admin codes --credits 100 --count 5  — коды пакетов генераций
  python -m arturokai.admin list-codes                     — все коды и их статус
"""
import argparse
import getpass
import sys

from .config import load_config
from .store import Store, StoreError


def main(argv=None):
    cfg = load_config()
    store = Store(cfg["billing"]["db"], cfg["billing"]["plans"])
    ap = argparse.ArgumentParser(prog="python -m arturokai.admin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin", help="создать администратора или сделать им существующего пользователя")
    a.add_argument("login")
    c = sub.add_parser("codes", help="создать коды для продажи")
    c.add_argument("--plan", help="тариф подписки: " + ", ".join(p for p in cfg["billing"]["plans"] if p != "free"))
    c.add_argument("--days", type=int, help="на сколько дней (по умолчанию — из тарифа)")
    c.add_argument("--credits", type=int, help="кредиты (для пакета генераций или чтобы изменить тариф)")
    c.add_argument("--count", type=int, default=1)
    c.add_argument("--note", default="")
    sub.add_parser("list-codes", help="показать все коды")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "create-admin":
            pw = getpass.getpass("Пароль (Enter — оставить прежний): ")
            u = store.set_admin(args.login, pw or None)
            print(f"Администратор: {u['login']}")
        elif args.cmd == "codes":
            kind = "plan" if args.plan else "credits"
            for code in store.create_codes(kind, args.count, args.plan, args.days, args.credits, args.note):
                print(code)
        else:
            for c in store.list_codes():
                what = f"{c['plan']} {c['days']} дн." if c["kind"] == "plan" else f"{c['credits']} кредитов"
                status = f"активирован: {c['used_login']}" if c["used_by"] else "свободен"
                print(f"{c['code']}  {what:<18} {status}  {c['note']}")
    except StoreError as e:
        sys.exit(f"Ошибка: {e}")


if __name__ == "__main__":
    main()
