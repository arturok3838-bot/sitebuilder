"""Чат и генерация кода через локальный сервер Ollama — без облака и без интернета.

Скорость:
- keep_alive держит модель в памяти между вопросами (нет перезагрузки ~5–30 с);
- warmup() загружает модель заранее, при старте сайта;
- без ZIP используется короткий контекст — модель быстрее начинает отвечать;
- в «быстром» режиме отвечает лёгкая модель.
"""
import json
import threading

import requests

STATS_MARK = "\x00"  # после этого символа в потоке идёт JSON со статистикой скорости


class LocalLLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.http = requests.Session()  # одно соединение на все запросы

    def available_models(self) -> list[str]:
        try:
            r = self.http.get(f"{self.cfg['host']}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []

    def effort(self, effort: str) -> dict:
        efforts = self.cfg["efforts"]
        return efforts.get(effort, efforts["medium"])

    def model_for(self, effort: str, model: str | None = None) -> str:
        if model:
            return model
        use = self.effort(effort)["use"]
        return self.cfg["model"] if use == "precise" else self.cfg["fast_model"]

    def num_ctx(self, context: str) -> int:
        # Без ZIP хватает короткого контекста; Ollama перезагружает модель при смене
        # num_ctx, поэтому значений всего два, а не подбор под каждый запрос.
        return self.cfg["num_ctx_project"] if context else self.cfg["num_ctx"]

    def warmup(self, model: str, context: str = "", background=True):
        """Загружает модель в память заранее, чтобы первый ответ пришёл сразу."""
        def run():
            try:
                self.http.post(f"{self.cfg['host']}/api/generate", timeout=300, json={
                    "model": model, "keep_alive": self.cfg["keep_alive"],
                    "options": {"num_ctx": self.num_ctx(context)}})
            except requests.RequestException:
                pass
        if background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()

    def chat_stream(self, messages: list[dict], model: str | None = None, context: str = "",
                    effort: str = "medium", explain: bool = False):
        system = self.cfg["system_prompt"]
        if explain:
            system += ("\n\nПользователь просит ПОДРОБНОЕ ОБЪЯСНЕНИЕ: разложи решение "
                       "по шагам, поясни, почему так, и прокомментируй ключевые строки кода.")
        if context:
            system += "\n\nФайлы пользователя из ZIP-архива:\n" + context
        model = self.model_for(effort, model)
        # Старые сообщения не отправляем — длинная история замедляет каждый ответ.
        messages = messages[-int(self.cfg["max_history"]):]
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
            "keep_alive": self.cfg["keep_alive"],
            "options": {"temperature": float(self.cfg["temperature"]), "num_ctx": self.num_ctx(context),
                        "num_predict": int(self.effort(effort)["num_predict"])},
        }
        try:
            with self.http.post(f"{self.cfg['host']}/api/chat", json=payload, stream=True, timeout=600) as r:
                if r.status_code == 404:
                    yield f"⚠️ Модель `{model}` не установлена. Выполните: `ollama pull {model}`"
                    return
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise RuntimeError(chunk["error"])
                    yield chunk.get("message", {}).get("content", "")
                    if chunk.get("done"):
                        yield STATS_MARK + json.dumps(speed_stats(chunk, model))
                        break
        except requests.ConnectionError:
            yield ("\n⚠️ Ollama не запущена. Установите с https://ollama.com и выполните:\n"
                   f"`ollama pull {model}`")


def speed_stats(done_chunk: dict, model: str) -> dict:
    """Ollama отдаёт длительности в наносекундах."""
    ns = 1e9
    tokens = done_chunk.get("eval_count", 0)
    gen = done_chunk.get("eval_duration", 0) / ns
    return {
        "model": model,
        "tokens": tokens,
        "tok_per_s": round(tokens / gen, 1) if gen else 0,
        "load_s": round(done_chunk.get("load_duration", 0) / ns, 2),
        "total_s": round(done_chunk.get("total_duration", 0) / ns, 2),
    }
