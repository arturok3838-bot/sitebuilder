"""Встроенная модель — работает БЕЗ ключа и БЕЗ интернета (после первой загрузки).

Это маленькая открытая модель (по умолчанию Qwen2.5-Coder-1.5B), которая крутится
прямо в сервере через transformers. Нужна, чтобы бесплатный тариф отвечал «из
коробки», ничего не подключая. На процессоре отвечает медленно и качество скромное —
для сильных ответов есть внешние движки (DeepSeek/ChatGPT) и видео по API.
"""
import importlib.util
import json
import threading
import time

from .llm import STATS_MARK

_model = None
_tok = None
_load_lock = threading.Lock()
_gen_lock = threading.Lock()   # одна генерация за раз (модель не потоко-параллельна)


def available(llm_cfg: dict) -> bool:
    b = llm_cfg.get("builtin") or {}
    return bool(b.get("enabled")) and importlib.util.find_spec("transformers") is not None


def _load(model_id: str):
    global _model, _tok
    with _load_lock:
        if _model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            _tok = AutoTokenizer.from_pretrained(model_id)
            _model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float32)
    return _model, _tok


def warmup(llm_cfg: dict):
    def run():
        try:
            _load(llm_cfg["builtin"]["model"])
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def chat_stream(llm_cfg: dict, messages: list[dict], system: str, max_new_tokens: int):
    b = llm_cfg["builtin"]
    try:
        model, tok = _load(b["model"])
    except Exception as e:
        yield f"⚠️ Не удалось загрузить встроенную модель: {e}"
        return
    from transformers import TextIteratorStreamer

    history = messages[-int(llm_cfg["max_history"]):]
    chat = [{"role": "system", "content": system}, *history]
    text = tok.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
    ins = tok(text, return_tensors="pt")
    cap = int(b.get("max_new_tokens_cap", 512))     # ограничение, чтобы на CPU не висеть долго
    streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True)
    kwargs = dict(**ins, max_new_tokens=min(int(max_new_tokens), cap), do_sample=False,
                  pad_token_id=tok.eos_token_id, streamer=streamer)

    with _gen_lock:
        t0 = time.time()
        thread = threading.Thread(target=model.generate, kwargs=kwargs)
        thread.start()
        n = 0
        for piece in streamer:
            n += 1
            yield piece
        thread.join()
    gen = max(time.time() - t0, 1e-6)
    yield STATS_MARK + json.dumps({"model": b["model"].split("/")[-1], "tokens": n,
                                   "tok_per_s": round(n / gen, 1), "load_s": 0, "total_s": round(gen, 2)})
