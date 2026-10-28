"""Аккаунты, сессии, тарифы, кредиты и коды активации (SQLite, без внешних сервисов).

Кредиты пользователя:
- credits — кредиты тарифа: у бесплатного обновляются каждые reset_days,
  у платного выдаются при активации и сгорают, когда подписка закончилась;
- bonus — кредиты из пакетов генераций, не сгорают и тратятся после тарифных.
Процент в личном кабинете — это credits / quota (сколько осталось от тарифа).
"""
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

DAY = 86400
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без похожих 0/O и 1/I

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    plan TEXT NOT NULL,
    plan_until REAL,
    credits INTEGER NOT NULL,
    quota INTEGER NOT NULL,
    period_start REAL NOT NULL,
    bonus INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS codes (
    code TEXT PRIMARY KEY,
    kind TEXT NOT NULL,           -- plan | credits
    plan TEXT,
    days INTEGER,
    credits INTEGER,
    note TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    used_by INTEGER REFERENCES users(id),
    used_at REAL
);
CREATE TABLE IF NOT EXISTS files (
    name TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,           -- image | video | upload
    prompt TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL            -- JSON; сюда админ сохраняет переопределения цен
);
CREATE TABLE IF NOT EXISTS sheets (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    cols INTEGER NOT NULL,
    rows INTEGER NOT NULL,
    data TEXT NOT NULL,           -- JSON: двумерный массив текста ячеек (формулы — как есть)
    updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    cost INTEGER NOT NULL,
    created REAL NOT NULL
);
"""


class StoreError(ValueError):
    """Ошибка, текст которой можно показать пользователю."""


class NotEnoughCredits(StoreError):
    pass


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, digest = stored.split("$")
    check = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return hmac.compare_digest(check, digest)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_email(value: str) -> bool:
    return bool(EMAIL_RE.match(value.strip()))


def new_code() -> str:
    groups = ("".join(secrets.choice(CODE_ALPHABET) for _ in range(4)) for _ in range(3))
    return "ARTK-" + "-".join(groups)


class Store:
    def __init__(self, path: str | Path, plans: dict, costs: dict | None = None):
        self.plans = plans          # эти словари меняются «на месте», когда админ правит цены,
        self.costs = costs or {}    # поэтому все, кто держит ссылку, сразу видят новые цены
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)
        self._apply_pricing()

    # ---------- цены (переопределения админа поверх config.yaml) ----------
    def _apply_pricing(self):
        """Накладывает сохранённые админом цены на словари plans/costs (на месте)."""
        row = self.db.execute("SELECT value FROM settings WHERE key = 'pricing'").fetchone()
        if not row:
            return
        data = json.loads(row["value"])
        for k, v in data.get("costs", {}).items():
            if k in self.costs:
                self.costs[k] = int(v)
        for plan_id, fields in data.get("plans", {}).items():
            if plan_id in self.plans:
                for f in ("price", "credits"):
                    if f in fields:
                        self.plans[plan_id][f] = fields[f]

    def get_pricing(self) -> dict:
        return {
            "costs": dict(self.costs),
            "plans": {k: {"name": p["name"], "price": p.get("price", ""), "credits": p.get("credits", 0)}
                      for k, p in self.plans.items()},
        }

    def set_pricing(self, data: dict):
        costs = {k: int(v) for k, v in data.get("costs", {}).items() if k in self.costs and int(v) >= 0}
        plans = {}
        for plan_id, fields in data.get("plans", {}).items():
            if plan_id not in self.plans:
                continue
            clean = {}
            if "price" in fields:
                clean["price"] = str(fields["price"])[:40]
            if "credits" in fields and int(fields["credits"]) >= 0:
                clean["credits"] = int(fields["credits"])
            if clean:
                plans[plan_id] = clean
        payload = json.dumps({"costs": costs, "plans": plans})
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('pricing', ?)", (payload,))
            self.db.commit()
            self._apply_pricing()

    # ---------- пользователи ----------
    def create_user(self, login: str, password: str, is_admin=False) -> dict:
        login = login.strip()
        if is_email(login):
            if len(login) > 254:
                raise StoreError("Слишком длинный email")
        elif not (3 <= len(login) <= 32 and all(c.isalnum() or c in "_.-" for c in login)):
            raise StoreError("Введите email или логин (3–32 символа: буквы, цифры, _ . -)")
        if len(password) < 6:
            raise StoreError("Пароль — минимум 6 символов")
        free = self.plans["free"]
        now = time.time()
        with self.lock:
            try:
                cur = self.db.execute(
                    "INSERT INTO users (login, pw, is_admin, plan, credits, quota, period_start, created)"
                    " VALUES (?, ?, ?, 'free', ?, ?, ?, ?)",
                    (login, hash_password(password), int(is_admin), free["credits"], free["credits"], now, now))
            except sqlite3.IntegrityError:
                raise StoreError("Такой логин уже занят")
            self.db.commit()
            return self.user(cur.lastrowid)

    def set_admin(self, login: str, password: str | None = None):
        with self.lock:
            row = self.db.execute("SELECT id FROM users WHERE login = ?", (login,)).fetchone()
            if row is None:
                return self.create_user(login, password or "", is_admin=True)
            self.db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (row["id"],))
            if password:
                self.db.execute("UPDATE users SET pw = ? WHERE id = ?", (hash_password(password), row["id"]))
            self.db.commit()
            return self.user(row["id"])

    def authenticate(self, login: str, password: str) -> dict | None:
        row = self.db.execute("SELECT id, pw FROM users WHERE login = ?", (login.strip(),)).fetchone()
        if row and verify_password(password, row["pw"]):
            return self.user(row["id"])
        return None

    def user(self, user_id: int) -> dict | None:
        """Пользователь с актуальным состоянием тарифа (истечение подписки, ежедневное обновление)."""
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                return None
            u = dict(row)
            now = time.time()
            if u["plan"] != "free" and (u["plan_until"] or 0) <= now:
                free = self.plans["free"]
                u.update(plan="free", plan_until=None, credits=free["credits"], quota=free["credits"], period_start=now)
            else:
                reset = self.plans.get(u["plan"], {}).get("reset_days")
                if reset and now - u["period_start"] >= reset * DAY:
                    quota = self.plans[u["plan"]]["credits"]
                    u.update(credits=quota, quota=quota, period_start=now)
            if u != dict(row):
                self.db.execute(
                    "UPDATE users SET plan=?, plan_until=?, credits=?, quota=?, period_start=? WHERE id=?",
                    (u["plan"], u["plan_until"], u["credits"], u["quota"], u["period_start"], u["id"]))
                self.db.commit()
            del u["pw"]
            return u

    def summary(self, u: dict) -> dict:
        """То, что видит пользователь в личном кабинете."""
        plan = self.plans.get(u["plan"], self.plans["free"])
        now = time.time()
        reset = plan.get("reset_days")
        return {
            "login": u["login"], "is_admin": bool(u["is_admin"]),
            "plan": u["plan"], "plan_name": plan["name"],
            "plan_until": u["plan_until"],
            "days_left": math.ceil((u["plan_until"] - now) / DAY) if u["plan_until"] else None,
            "resets_in_h": math.ceil((u["period_start"] + reset * DAY - now) / 3600) if reset else None,
            "credits": u["credits"], "quota": u["quota"], "bonus": u["bonus"],
            "percent": round(100 * u["credits"] / u["quota"]) if u["quota"] else 0,
            "total": u["credits"] + u["bonus"],
            "limits": {k: plan.get(k) for k in ("max_image_side", "max_images", "video_max_seconds",
                                            "chat_modes", "zip", "external")},
        }

    # ---------- сессии ----------
    def new_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token, user_id, time.time()))
            self.db.commit()
        return token

    def session_user(self, token: str | None, max_age_days=30) -> dict | None:
        if not token:
            return None
        row = self.db.execute("SELECT user_id, created FROM sessions WHERE token = ?", (token,)).fetchone()
        if row is None or time.time() - row["created"] > max_age_days * DAY:
            return None
        return self.user(row["user_id"])

    def drop_session(self, token: str):
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            self.db.commit()

    # ---------- кредиты ----------
    def charge(self, user_id: int, cost: int, action: str):
        """Списывает кредиты: сначала тарифные, потом бонусные."""
        with self.lock:
            u = self.user(user_id)
            if u["credits"] + u["bonus"] < cost:
                raise NotEnoughCredits(
                    f"Недостаточно кредитов: нужно {cost}, осталось {u['credits'] + u['bonus']}. "
                    "Активируйте код в личном кабинете.")
            from_plan = min(cost, u["credits"])
            self.db.execute("UPDATE users SET credits = credits - ?, bonus = bonus - ? WHERE id = ?",
                            (from_plan, cost - from_plan, user_id))
            self.db.execute("INSERT INTO usage (user_id, action, cost, created) VALUES (?, ?, ?, ?)",
                            (user_id, action, cost, time.time()))
            self.db.commit()

    def refund(self, user_id: int, cost: int, action: str):
        with self.lock:
            self.db.execute("UPDATE users SET bonus = bonus + ? WHERE id = ?", (cost, user_id))
            self.db.execute("INSERT INTO usage (user_id, action, cost, created) VALUES (?, ?, ?, ?)",
                            (user_id, action, -cost, time.time()))
            self.db.commit()

    def usage(self, user_id: int, limit=30) -> list[dict]:
        rows = self.db.execute("SELECT action, cost, created FROM usage WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                               (user_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---------- коды ----------
    def create_codes(self, kind: str, count: int, plan: str | None = None, days: int | None = None,
                     credits: int | None = None, note: str = "") -> list[str]:
        if kind == "plan":
            if plan not in self.plans or plan == "free":
                raise StoreError("Выберите платный тариф")
            days = int(days or self.plans[plan].get("days", 30))
            credits = int(credits or self.plans[plan]["credits"])
        elif kind == "credits":
            if not credits or credits <= 0:
                raise StoreError("Укажите количество кредитов")
            plan = days = None
        else:
            raise StoreError("Неизвестный тип кода")
        if not 1 <= count <= 1000:
            raise StoreError("Количество: от 1 до 1000")
        codes, now = [], time.time()
        with self.lock:
            while len(codes) < count:
                code = new_code()
                try:
                    self.db.execute("INSERT INTO codes (code, kind, plan, days, credits, note, created)"
                                    " VALUES (?, ?, ?, ?, ?, ?, ?)", (code, kind, plan, days, credits, note, now))
                    codes.append(code)
                except sqlite3.IntegrityError:
                    continue  # совпадение практически невозможно, но просто генерируем ещё раз
            self.db.commit()
        return codes

    def redeem(self, user_id: int, code: str) -> str:
        code = code.strip().upper()
        with self.lock:
            row = self.db.execute("SELECT * FROM codes WHERE code = ?", (code,)).fetchone()
            if row is None:
                raise StoreError("Код не найден — проверьте, что он введён без ошибок")
            if row["used_by"] is not None:
                raise StoreError("Этот код уже активирован")
            u = self.user(user_id)
            now = time.time()
            if row["kind"] == "credits":
                self.db.execute("UPDATE users SET bonus = bonus + ? WHERE id = ?", (row["credits"], user_id))
                message = f"Начислено {row['credits']} кредитов"
            else:
                plan = self.plans[row["plan"]]
                if u["plan"] == row["plan"]:
                    # Тот же тариф — продлеваем и добавляем кредиты.
                    until = u["plan_until"] + row["days"] * DAY
                    credits, quota = u["credits"] + row["credits"], u["quota"] + row["credits"]
                else:
                    until, credits, quota = now + row["days"] * DAY, row["credits"], row["credits"]
                self.db.execute("UPDATE users SET plan=?, plan_until=?, credits=?, quota=?, period_start=? WHERE id=?",
                                (row["plan"], until, credits, quota, now, user_id))
                message = f"Тариф «{plan['name']}» активен на {row['days']} дн., {row['credits']} кредитов"
            self.db.execute("UPDATE codes SET used_by = ?, used_at = ? WHERE code = ?", (user_id, now, code))
            self.db.execute("INSERT INTO usage (user_id, action, cost, created) VALUES (?, ?, 0, ?)",
                            (user_id, f"Код {code}: {message}", now))
            self.db.commit()
            return message

    def list_codes(self, limit=500) -> list[dict]:
        rows = self.db.execute(
            "SELECT c.*, u.login AS used_login FROM codes c LEFT JOIN users u ON u.id = c.used_by"
            " ORDER BY c.created DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def list_users(self) -> list[dict]:
        rows = self.db.execute("SELECT id FROM users ORDER BY created DESC").fetchall()
        users = [self.user(r["id"]) for r in rows]
        return [self.summary(u) | {"created": u["created"]} for u in users]

    # ---------- файлы ----------
    def add_file(self, name: str, user_id: int, kind: str, prompt: str = ""):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?)",
                            (name, user_id, kind, prompt, time.time()))
            self.db.commit()

    def file_owner(self, name: str) -> int | None:
        row = self.db.execute("SELECT user_id FROM files WHERE name = ?", (name,)).fetchone()
        return row["user_id"] if row else None

    def files(self, user_id: int, limit=200) -> list[dict]:
        rows = self.db.execute("SELECT name, kind, prompt, created FROM files WHERE user_id = ? AND kind != 'upload'"
                               " ORDER BY created DESC LIMIT ?", (user_id, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---------- таблицы пользователя ----------
    def list_sheets(self, user_id: int) -> list[dict]:
        rows = self.db.execute("SELECT id, name, updated FROM sheets WHERE user_id = ? ORDER BY updated DESC",
                               (user_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_sheet(self, sheet_id: int, user_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM sheets WHERE id = ? AND user_id = ?", (sheet_id, user_id)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["data"] = json.loads(d["data"])
        return d

    def create_sheet(self, user_id: int, name: str, rows=10, cols=6) -> dict:
        name = (name or "Таблица").strip()[:60]
        data = [["" for _ in range(cols)] for _ in range(rows)]
        now = time.time()
        with self.lock:
            cur = self.db.execute("INSERT INTO sheets (user_id, name, cols, rows, data, updated)"
                                  " VALUES (?, ?, ?, ?, ?, ?)", (user_id, name, cols, rows, json.dumps(data), now))
            self.db.commit()
            return self.get_sheet(cur.lastrowid, user_id)

    def save_sheet(self, sheet_id: int, user_id: int, name: str, rows: int, cols: int, data: list):
        if self.get_sheet(sheet_id, user_id) is None:
            raise StoreError("Таблица не найдена")
        rows, cols = max(1, min(int(rows), 200)), max(1, min(int(cols), 50))
        # Приводим размер данных к rows×cols и обрезаем длину текста ячейки.
        grid = [[str(data[r][c])[:500] if r < len(data) and c < len(data[r]) else ""
                 for c in range(cols)] for r in range(rows)]
        with self.lock:
            self.db.execute("UPDATE sheets SET name = ?, cols = ?, rows = ?, data = ?, updated = ? WHERE id = ? AND user_id = ?",
                            ((name or "Таблица").strip()[:60], cols, rows, json.dumps(grid), time.time(), sheet_id, user_id))
            self.db.commit()
        return self.get_sheet(sheet_id, user_id)

    def delete_sheet(self, sheet_id: int, user_id: int):
        with self.lock:
            self.db.execute("DELETE FROM sheets WHERE id = ? AND user_id = ?", (sheet_id, user_id))
            self.db.commit()
