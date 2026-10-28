import copy
import io
import json
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from arturokai import server
from arturokai.store import Store


class FakeImage:
    def __init__(self):
        self.calls = []

    def generate(self, prompt, negative, w, h, steps, seed, count, ref=None, strength=0.6):
        self.calls.append(dict(prompt=prompt, ref=ref, strength=strength))
        if prompt == "сломать":
            raise RuntimeError("CUDA out of memory")
        paths = []
        for _ in range(count):
            p = server.OUT / f"test_{time.time_ns()}.png"
            Image.new("RGB", (8, 8)).save(p)
            paths.append(p)
        return paths


class FakeVideo:
    def generate(self, prompt, seconds, negative, start, seed, steps, progress):
        progress(0.5, desc="Сегмент 1/2")
        p = server.OUT / f"test_{time.time_ns()}.mp4"
        p.write_bytes(b"0")
        return p


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    # Цены меняются «на месте» в общих словарях — сохраняем и восстанавливаем их.
    saved_plans, saved_costs = copy.deepcopy(server.PLANS), copy.deepcopy(server.COSTS)
    server.store = Store(tmp_path / "db.sqlite", server.PLANS, server.COSTS)
    server.rate_limiter.enabled = False
    server._login_fails.clear()
    server._gens.update(image=FakeImage(), video=FakeVideo())
    yield
    server.PLANS.clear(); server.PLANS.update(saved_plans)
    server.COSTS.clear(); server.COSTS.update(saved_costs)
    for p in server.OUT.glob("test_*"):
        p.unlink()


def client(login="artur", admin=False):
    c = TestClient(server.app)
    if admin:
        server.store.set_admin(login, "secret1")
        assert c.post("/api/login", json={"login": login, "password": "secret1"}).status_code == 200
    else:
        assert c.post("/api/register", json={"login": login, "password": "secret1"}).status_code == 200
    return c


def wait(c, job_id):
    for _ in range(200):
        job = c.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.02)
    raise AssertionError("задача не завершилась")


def png():
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    return buf.getvalue()


def test_site_and_plans_public():
    c = TestClient(server.app)
    assert "ARTurokAI" in c.get("/").text
    plans = c.get("/api/plans").json()
    assert [p["id"] for p in plans["plans"]] == ["free", "start", "pro"]
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/image", json={"prompt": "кот"}).status_code == 401


def test_free_plan_image_by_text_and_by_example():
    c = client()
    me = c.get("/api/me").json()
    assert (me["plan"], me["percent"], me["credits"]) == ("free", 100, 30)

    done = wait(c, c.post("/api/image", json={"prompt": "кот", "width": 768, "height": 768}).json()["id"])
    assert done["status"] == "done" and c.get(done["result"][0]).status_code == 200

    ref = c.post("/api/upload-image", files={"file": ("a.png", png())}).json()["name"]
    job = c.post("/api/image", json={"prompt": "в стиле аниме", "width": 768, "height": 768,
                                     "ref_image": ref, "strength": 0.4}).json()
    assert wait(c, job["id"])["status"] == "done"
    call = server._gens["image"].calls[-1]
    assert call["ref"] is not None and call["strength"] == 0.4

    me = c.get("/api/me").json()
    assert (me["credits"], me["percent"]) == (26, 87)
    assert len(c.get("/api/gallery").json()) == 2


def test_free_plan_limits():
    c = client()
    r = c.post("/api/image", json={"prompt": "кот", "width": 1024, "height": 1024})
    assert r.status_code == 403 and "768" in r.json()["detail"]
    assert c.post("/api/video", json={"prompt": "горы", "seconds": 5}).status_code == 403
    assert c.post("/api/chat", json={"messages": [], "effort": "high"}).status_code == 403
    assert c.post("/api/zip", files={"file": ("p.zip", b"x")}).status_code == 403


def test_not_enough_credits_and_refund_on_error():
    c = client()
    job = c.post("/api/image", json={"prompt": "сломать", "width": 512, "height": 512}).json()
    assert wait(c, job["id"])["status"] == "error"
    assert c.get("/api/me").json()["total"] == 30   # кредиты вернулись
    server.store.charge(server.store.authenticate("artur", "secret1")["id"], 30, "тест")
    r = c.post("/api/image", json={"prompt": "кот", "width": 512, "height": 512})
    assert r.status_code == 402 and "кабинете" in r.json()["detail"]


def test_admin_codes_and_paid_plan_video():
    admin = client("boss", admin=True)
    assert client("other").get("/api/admin/codes").status_code == 403
    codes = admin.post("/api/admin/codes", json={"kind": "plan", "plan": "start", "count": 2,
                                                 "note": "Авито"}).json()["codes"]
    pack = admin.post("/api/admin/codes", json={"kind": "credits", "credits": 100}).json()["codes"][0]

    c = client("buyer")
    assert "Старт" in c.post("/api/redeem", json={"code": codes[0]}).json()["message"]
    c.post("/api/redeem", json={"code": pack})
    me = c.get("/api/me").json()
    assert (me["plan"], me["credits"], me["bonus"], me["days_left"]) == ("start", 600, 100, 30)
    assert c.post("/api/redeem", json={"code": codes[0]}).status_code == 400

    job = c.post("/api/video", json={"prompt": "горы", "seconds": 10}).json()
    assert wait(c, job["id"])["status"] == "done"
    assert c.get("/api/me").json()["credits"] == 570
    assert c.post("/api/video", json={"prompt": "горы", "seconds": 60}).status_code == 403

    listed = {x["code"]: x for x in admin.get("/api/admin/codes").json()}
    assert listed[codes[0]]["used_login"] == "buyer" and listed[codes[1]]["used_by"] is None
    csv_text = admin.get("/api/admin/codes.csv?only_free=1").text
    assert codes[1] in csv_text and codes[0] not in csv_text
    assert any(u["login"] == "buyer" for u in admin.get("/api/admin/users").json())


def test_users_cannot_see_each_other():
    a, b = client("alice"), client("bob")
    done = wait(a, a.post("/api/image", json={"prompt": "кот", "width": 512, "height": 512}).json()["id"])
    assert b.get(done["result"][0]).status_code == 404
    assert b.get(f"/api/jobs/{done['id']}").status_code == 404
    assert b.get("/api/gallery").json() == []
    ref = a.post("/api/upload-image", files={"file": ("a.png", png())}).json()["name"]
    assert b.post("/api/image", json={"prompt": "x", "width": 512, "height": 512,
                                      "ref_image": ref}).status_code == 400


def test_login_logout_and_bruteforce():
    client("carl")
    c = TestClient(server.app)
    assert c.post("/api/login", json={"login": "carl", "password": "bad"}).status_code == 400
    assert c.post("/api/login", json={"login": "carl", "password": "secret1"}).status_code == 200
    assert c.get("/api/me").status_code == 200
    c.post("/api/logout")
    assert c.get("/api/me").status_code == 401
    server._login_fails.clear()
    for _ in range(10):
        c.post("/api/login", json={"login": "carl", "password": "bad"})
    assert c.post("/api/login", json={"login": "carl", "password": "secret1"}).status_code == 429
    server._login_fails.clear()


def test_zip_chat_refund_and_export():
    admin = client("boss2", admin=True)
    code = admin.post("/api/admin/codes", json={"kind": "plan", "plan": "pro"}).json()["codes"][0]
    c = client("dev")
    c.post("/api/redeem", json={"code": code})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("src/main.py", "print(1)")
    d = c.post("/api/zip", files={"file": ("p.zip", buf.getvalue())}).json()
    assert "main.py" in d["tree"]
    assert c.post("/api/zip", files={"file": ("bad.zip", b"not a zip")}).status_code == 400

    server.llm.cfg["host"] = "http://127.0.0.1:9"   # Ollama выключена
    before = c.get("/api/me").json()["total"]
    r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "effort": "high"})
    assert "Ollama" in r.text
    assert c.get("/api/me").json()["total"] == before  # кредит за неотвеченное сообщение вернулся

    r = c.post("/api/export", json={"text": "```python a.py\nx=1\n```"})
    assert r.headers["content-type"] == "application/zip"


def test_admin_can_change_prices_everyone_sees():
    admin = client("boss3", admin=True)
    buyer = client("buyer3")
    assert buyer.get("/api/plans").json()["costs"]["image"] == 2
    # не админ менять цены не может
    assert buyer.post("/api/admin/pricing", json={"costs": {"image": 9}}).status_code == 403
    admin.post("/api/admin/pricing", json={"costs": {"image": 9},
                                           "plans": {"start": {"price": "990 ₽", "credits": 1000}}})
    # новый пользователь сразу видит новую цену
    other = client("buyer3b")
    assert other.get("/api/plans").json()["costs"]["image"] == 9
    assert any(p["price"] == "990 ₽" for p in other.get("/api/plans").json()["plans"])
    # и она реально списывается: фото теперь стоит 9
    before = other.get("/api/me").json()["total"]
    wait(other, other.post("/api/image", json={"prompt": "кот", "width": 512, "height": 512}).json()["id"])
    assert other.get("/api/me").json()["total"] == before - 9


@pytest.fixture
def fake_openai():
    """Поддельная внешняя нейросеть по протоколу OpenAI."""
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for w in ["При", "вет"]:
                self.wfile.write(f'data: {json.dumps({"choices":[{"delta":{"content":w}}]})}\n\n'.encode())
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_external_engine(fake_openai, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    # направляем провайдера deepseek на поддельный сервер
    for p in server.llm.cfg["providers"]:
        if p["id"] == "deepseek":
            monkeypatch.setitem(p, "base_url", fake_openai)

    admin = client("boss4", admin=True)
    code = admin.post("/api/admin/codes", json={"kind": "plan", "plan": "pro"}).json()["codes"][0]
    c = client("buyer4")
    # на бесплатном тарифе внешние модели закрыты
    assert c.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}],
                                     "engine": "deepseek"}).status_code == 403
    c.post("/api/redeem", json={"code": code})
    assert "deepseek" in [p["id"] for p in c.get("/api/status").json()["providers"]]
    before = c.get("/api/me").json()["total"]
    r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "engine": "deepseek"})
    assert "Привет" in r.text
    assert c.get("/api/me").json()["total"] == before - server.COSTS["chat"] * 3


def test_sheets_api():
    a, b = client("sheeter"), client("sheeter2")
    s = a.post("/api/sheets", json={"name": "Бюджет", "rows": 3, "cols": 2}).json()
    a.put(f"/api/sheets/{s['id']}", json={"name": "Бюджет", "rows": 2, "cols": 2,
                                          "data": [["10", "20"], ["=A1+B1", ""]]})
    got = a.get(f"/api/sheets/{s['id']}").json()
    assert got["data"][0] == ["10", "20"] and got["rows"] == 2
    assert len(a.get("/api/sheets").json()) == 1
    # чужая таблица недоступна
    assert b.get(f"/api/sheets/{s['id']}").status_code == 404
    assert b.get("/api/sheets").json() == []
    a.delete(f"/api/sheets/{s['id']}")
    assert a.get("/api/sheets").json() == []


def test_free_engine_on_free_plan(fake_openai, monkeypatch):
    # Бесплатная модель (OpenRouter) должна работать на бесплатном тарифе.
    monkeypatch.setenv("OPENROUTER_API_KEY", "free-key")
    for p in server.llm.cfg["providers"]:
        if p["id"] == "free-auto":
            monkeypatch.setitem(p, "base_url", fake_openai)
    c = client("freeuser")
    provs = {p["id"]: p for p in c.get("/api/status").json()["providers"]}
    assert provs["free-auto"]["free"] is True          # помечена как бесплатная
    before = c.get("/api/me").json()["total"]
    r = c.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}], "engine": "free-auto"})
    assert "Привет" in r.text                            # ответ пришёл
    assert c.get("/api/me").json()["total"] == before - server.COSTS["chat"]  # cost_mult 1
    # платная модель на бесплатном тарифе — закрыта
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    assert c.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}],
                                     "engine": "deepseek"}).status_code == 403
