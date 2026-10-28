"""Загрузка секретов из файла .env (токен бота, ключи внешних нейросетей).

Файл .env лежит рядом с проектом и в .gitignore — в GitHub он НЕ попадает.
Формат построчно:  КЛЮЧ=значение   (строки с # — комментарии).
Значения из окружения имеют приоритет и не перезаписываются.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str | Path | None = None) -> list[str]:
    path = Path(path) if path else ROOT / ".env"
    if not path.is_file():
        return []
    loaded = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:   # окружение важнее файла
            os.environ[key] = value
            loaded.append(key)
    return loaded
