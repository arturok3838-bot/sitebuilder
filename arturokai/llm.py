"""Чат и генерация кода через локальный сервер Ollama — без облака и без интернета."""
import json

import requests


class LocalLLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg

    def available_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.cfg['host']}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []

    def chat_stream(self, messages: list[dict], model: str | None = None, context: str = ""):
        system = self.cfg["system_prompt"]
        if context:
            system += "\n\nФайлы пользователя из ZIP-архива:\n" + context
        payload = {
            "model": model or self.cfg["model"],
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            "options": {"temperature": float(self.cfg["temperature"]), "num_ctx": 32768},
        }
        try:
            with requests.post(f"{self.cfg['host']}/api/chat", json=payload, stream=True, timeout=600) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise RuntimeError(chunk["error"])
                    yield chunk.get("message", {}).get("content", "")
                    if chunk.get("done"):
                        break
        except requests.ConnectionError:
            yield ("\n⚠️ Ollama не запущена. Установите с https://ollama.com и выполните:\n"
                   f"`ollama pull {self.cfg['model']}`")
