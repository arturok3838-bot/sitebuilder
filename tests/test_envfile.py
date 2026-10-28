import os

from arturokai.envfile import load_env


def test_load_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# комментарий\nARTUROKAI_BOT_TOKEN="секрет123"\nDEEPSEEK_API_KEY=abc\n\nПУСТО\n', encoding="utf-8")
    monkeypatch.delenv("ARTUROKAI_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    loaded = load_env(f)
    assert "ARTUROKAI_BOT_TOKEN" in loaded and os.environ["ARTUROKAI_BOT_TOKEN"] == "секрет123"
    assert os.environ["DEEPSEEK_API_KEY"] == "abc"


def test_env_overrides_file(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("ARTUROKAI_SITE=from_file\n", encoding="utf-8")
    monkeypatch.setenv("ARTUROKAI_SITE", "from_env")
    load_env(f)
    assert os.environ["ARTUROKAI_SITE"] == "from_env"   # окружение важнее файла


def test_missing_file_ok(tmp_path):
    assert load_env(tmp_path / "нет.env") == []
