import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from arturokai.llm import STATS_MARK, LocalLLM

CFG = dict(host="", fast_model="fast:7b", model="big:14b", keep_alive="60m", temperature=0.3,
           num_ctx=8192, num_ctx_project=32768, max_history=4, system_prompt="sys",
           efforts={"low": {"label": "⚡", "use": "fast", "num_predict": 1024, "cost_mult": 1},
                    "medium": {"label": "⚖️", "use": "fast", "num_predict": 4096, "cost_mult": 2},
                    "high": {"label": "🎯", "use": "precise", "num_predict": 16384, "cost_mult": 4}})


@pytest.fixture
def ollama():
    """Поддельный Ollama: запоминает запросы и отвечает потоком из двух кусков."""
    seen = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, body))
            if body["model"] == "missing":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            if self.path == "/api/chat":
                for c in [{"message": {"content": "При"}}, {"message": {"content": "вет"}},
                          {"done": True, "eval_count": 100, "eval_duration": 2_000_000_000,
                           "load_duration": 0, "total_duration": 2_500_000_000}]:
                    self.wfile.write((json.dumps(c) + "\n").encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", seen
    srv.shutdown()


def test_fast_mode_stream_and_stats(ollama):
    host, seen = ollama
    llm = LocalLLM(CFG | {"host": host})
    msgs = [{"role": "user", "content": str(i)} for i in range(10)]
    out = "".join(llm.chat_stream(msgs, effort="low"))
    text, stats = out.split(STATS_MARK)
    assert text == "Привет"
    assert json.loads(stats) == {"model": "fast:7b", "tokens": 100, "tok_per_s": 50.0,
                                 "load_s": 0.0, "total_s": 2.5}
    body = seen[-1][1]
    assert body["keep_alive"] == "60m" and body["options"]["num_ctx"] == 8192
    assert body["options"]["num_predict"] == 1024
    assert len(body["messages"]) == 1 + 4  # системное + последние max_history


def test_precise_mode_and_project_context(ollama):
    host, seen = ollama
    llm = LocalLLM(CFG | {"host": host})
    list(llm.chat_stream([{"role": "user", "content": "x"}], context="файлы", effort="high"))
    body = seen[-1][1]
    assert body["model"] == "big:14b" and body["options"]["num_ctx"] == 32768
    assert body["options"]["num_predict"] == 16384
    assert "файлы" in body["messages"][0]["content"]


def test_explain_adds_instruction(ollama):
    host, seen = ollama
    llm = LocalLLM(CFG | {"host": host})
    list(llm.chat_stream([{"role": "user", "content": "x"}], effort="low", explain=True))
    assert "ОБЪЯСНЕНИЕ" in seen[-1][1]["messages"][0]["content"]


def test_warmup_and_missing_model(ollama):
    host, seen = ollama
    llm = LocalLLM(CFG | {"host": host})
    llm.warmup("fast:7b", background=False)
    assert seen[-1][0] == "/api/generate" and seen[-1][1]["keep_alive"] == "60m"
    out = "".join(llm.chat_stream([{"role": "user", "content": "x"}], model="missing"))
    assert "ollama pull missing" in out


def test_ollama_down():
    llm = LocalLLM(CFG | {"host": "http://127.0.0.1:9"})
    assert "Ollama не запущена" in "".join(llm.chat_stream([{"role": "user", "content": "x"}]))
