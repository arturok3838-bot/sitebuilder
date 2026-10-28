"""Сайт ARTurokAI. Запуск: python -m arturokai.server  →  http://127.0.0.1:7860

Доступ к генерации — по аккаунтам и кредитам. Кредиты дают тарифы: бесплатный
(обновляется каждый день) и платные, которые активируются кодами. Коды создаёт
администратор (в админ-панели сайта или командой python -m arturokai.admin).

Генерация фото и видео идёт через очередь задач: видеокарта одна, поэтому задачи
выполняются по очереди (платные тарифы — раньше) в фоновом потоке.
"""
import argparse
import csv
import io
import itertools
import math
import os
import queue
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from .config import ROOT, load_config
from .envfile import load_env
from .llm import STATS_MARK, LocalLLM
from .security import install as install_security
from .store import NotEnoughCredits, Store, StoreError
from .zip_tools import ZipError, build_context, code_blocks_to_zip, safe_extract, tree

load_env()               # ключи внешних нейросетей (DEEPSEEK_API_KEY и т. п.) из .env
cfg = load_config()
OUT, WS = cfg["output_dir"], cfg["workspace_dir"]
WEB = ROOT / "web"
BILL = cfg["billing"]
PLANS, COSTS = BILL["plans"], BILL["costs"]
COOKIE = "arturokai_session"

llm = LocalLLM(cfg["llm"])
store = Store(BILL["db"], PLANS, COSTS)


def ensure_admin():
    """Создаёт администратора из переменных окружения (ARTUROKAI_ADMIN_LOGIN/PASSWORD).

    Удобно для первого запуска: задали логин и пароль в .env — админ появился сам.
    """
    login = os.environ.get("ARTUROKAI_ADMIN_LOGIN")
    password = os.environ.get("ARTUROKAI_ADMIN_PASSWORD")
    if login and password:
        store.set_admin(login, password)
        print(f"Администратор готов: {login}")


app = FastAPI(title="ARTurokAI")
rate_limiter = install_security(app, cfg)
jobs: dict[str, dict] = {}
job_queue: queue.PriorityQueue = queue.PriorityQueue()
_order = itertools.count()       # при равном приоритете — кто раньше пришёл
projects: dict[str, tuple[int, str]] = {}   # id ZIP-проекта -> (владелец, контекст для модели)
_gens: dict = {}
_login_fails: dict[str, list[float]] = {}


def generator(kind: str):
    """Модели грузятся только при первом использовании — сайт стартует мгновенно."""
    if kind not in _gens:
        if kind == "image":
            from .image_gen import ImageGenerator
            _gens[kind] = ImageGenerator(cfg["image"], OUT)
        else:
            from .video_gen import VideoGenerator
            _gens[kind] = VideoGenerator(cfg["video"], OUT)
    return _gens[kind]


# ---------- пользователи ----------
def current_user(request: Request) -> dict:
    u = store.session_user(request.cookies.get(COOKIE))
    if u is None:
        raise HTTPException(401, "Войдите в аккаунт")
    return u


def admin_user(u: dict = Depends(current_user)) -> dict:
    if not u["is_admin"]:
        raise HTTPException(403, "Только для администратора")
    return u


def plan_of(u: dict) -> dict:
    return PLANS.get(u["plan"], PLANS["free"])


def charge(u: dict, cost: int, action: str):
    try:
        store.charge(u["id"], cost, action)
    except NotEnoughCredits as e:
        raise HTTPException(402, str(e))


def upload_path(name: str, u: dict) -> Path:
    if store.file_owner(name) != u["id"]:
        raise HTTPException(400, "Файл не найден, загрузите его заново")
    return WS / name


# ---------- очередь задач ----------
def file_url(path: Path) -> str:
    return f"/files/{path.name}"


def run_job(job: dict):
    p = job["params"]

    def progress(frac, desc=""):
        job["progress"], job["desc"] = float(frac), desc

    if job["kind"] == "image":
        job["desc"] = "Загрузка модели и генерация…"
        ref = Image.open(WS / p["ref_image"]) if p.get("ref_image") else None
        paths = generator("image").generate(p["prompt"], p["negative"], p["width"], p["height"],
                                            p["steps"], p["seed"], p["count"], ref, p["strength"])
    else:
        start = Image.open(WS / p["start_image"]) if p.get("start_image") else None
        paths = [generator("video").generate(p["prompt"], p["seconds"], p["negative"], start,
                                             p["seed"], p["steps"], progress)]
    for path in paths:
        store.add_file(path.name, job["user_id"], job["kind"], p["prompt"])
    job["result"] = [file_url(x) for x in paths]


def worker():
    while True:
        *_, job = job_queue.get()
        job["status"], job["started"] = "running", time.time()
        try:
            run_job(job)
            job["status"], job["progress"] = "done", 1.0
        except Exception as e:  # ошибку показываем на сайте, кредиты возвращаем
            job["status"], job["error"] = "error", str(e)
            store.refund(job["user_id"], job["cost"], "Возврат: ошибка генерации")
        job["finished"] = time.time()


threading.Thread(target=worker, daemon=True).start()
if cfg["llm"].get("preload"):
    llm.warmup(cfg["llm"]["fast_model"])


def submit(u: dict, kind: str, params: dict, cost: int) -> dict:
    # Защита очереди от флуда: не даём одному пользователю забить её задачами.
    pending = sum(1 for j in jobs.values()
                  if j["user_id"] == u["id"] and j["status"] in ("queued", "running"))
    if pending >= int(cfg["security"]["max_pending_jobs"]):
        raise HTTPException(429, "Дождитесь завершения текущих задач")
    charge(u, cost, "Фото" if kind == "image" else f"Видео {params['seconds']:g} сек")
    job = dict(id=uuid.uuid4().hex[:12], kind=kind, params=params, user_id=u["id"], cost=cost,
               status="queued", progress=0.0, desc="В очереди", result=[], error=None, created=time.time())
    jobs[job["id"]] = job
    job_queue.put((plan_of(u).get("priority", 1), next(_order), job))
    return public(job)


def public(job: dict) -> dict:
    hidden = ("params", "user_id")
    return {k: v for k, v in job.items() if k not in hidden} | {"prompt": job["params"]["prompt"]}


# ---------- модели запросов ----------
class AuthReq(BaseModel):
    login: str
    password: str


class CodeReq(BaseModel):
    code: str


class NewCodesReq(BaseModel):
    kind: Literal["plan", "credits"]
    plan: str | None = None
    days: int | None = Field(None, ge=1, le=3650)
    credits: int | None = Field(None, ge=1, le=10_000_000)
    count: int = Field(1, ge=1, le=1000)
    note: str = ""


class ImageReq(BaseModel):
    prompt: str = Field(min_length=1)
    negative: str = ""
    width: int = Field(cfg["image"]["width"], ge=256, le=2048)
    height: int = Field(cfg["image"]["height"], ge=256, le=2048)
    steps: int = Field(cfg["image"]["steps"], ge=1, le=100)
    seed: int = -1
    count: int = Field(1, ge=1, le=4)
    ref_image: str | None = None     # пример фото из /api/upload-image
    strength: float = Field(0.6, ge=0.1, le=0.95)


class VideoReq(BaseModel):
    prompt: str = Field(min_length=1)
    negative: str = ""
    seconds: float = Field(5, ge=1, le=cfg["video"]["max_seconds"])
    steps: int = Field(cfg["video"]["steps"], ge=5, le=100)
    seed: int = -1
    start_image: str | None = None


class ChatReq(BaseModel):
    messages: list[dict]
    model: str | None = None          # явный выбор модели — только для администратора
    effort: Literal["low", "medium", "high"] = "medium"
    engine: str = "local"             # "local" или id внешней нейросети (deepseek/kimi/openai)
    explain: bool = False             # подробное объяснение решения
    project_id: str | None = None


class WarmupReq(BaseModel):
    model: str | None = None
    effort: Literal["low", "medium", "high"] = "medium"
    engine: str = "local"
    project_id: str | None = None


class ExportReq(BaseModel):
    text: str


class PricingReq(BaseModel):
    costs: dict[str, int] = {}
    plans: dict[str, dict] = {}


class SheetReq(BaseModel):
    name: str = "Таблица"
    rows: int = Field(10, ge=1, le=200)
    cols: int = Field(6, ge=1, le=50)
    data: list[list[str]] = []


# ---------- аккаунт ----------
def start_session(response: Response, u: dict) -> dict:
    response.set_cookie(COOKIE, store.new_session(u["id"]), max_age=30 * 86400,
                        httponly=True, samesite="lax")
    return store.summary(u)


@app.post("/api/register")
def register(req: AuthReq, response: Response):
    try:
        u = store.create_user(req.login, req.password)
    except StoreError as e:
        raise HTTPException(400, str(e))
    return start_session(response, u)


@app.post("/api/login")
def login(req: AuthReq, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.time()
    fails = [t for t in _login_fails.get(ip, []) if now - t < 600]
    if len(fails) >= 10:
        raise HTTPException(429, "Слишком много попыток. Подождите 10 минут.")
    u = store.authenticate(req.login, req.password)
    if u is None:
        _login_fails[ip] = fails + [now]
        raise HTTPException(400, "Неверный логин или пароль")
    _login_fails.pop(ip, None)
    return start_session(response, u)


@app.post("/api/logout")
def logout(request: Request, response: Response):
    if request.cookies.get(COOKIE):
        store.drop_session(request.cookies[COOKIE])
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me")
def me(u: dict = Depends(current_user)):
    return store.summary(u) | {"usage": store.usage(u["id"])}


@app.post("/api/redeem")
def redeem(req: CodeReq, u: dict = Depends(current_user)):
    try:
        message = store.redeem(u["id"], req.code)
    except StoreError as e:
        raise HTTPException(400, str(e))
    return {"message": message, "me": store.summary(store.user(u["id"]))}


@app.get("/api/plans")
def plans():
    return {"plans": [{"id": k, "name": p["name"], "price": p["price"], "includes": p["includes"]}
                      for k, p in PLANS.items()],
            "contact": BILL["seller_contact"], "costs": COSTS}


@app.get("/api/status")
def status(u: dict = Depends(current_user)):
    efforts = {k: {"label": e["label"], "use": e["use"], "cost": COSTS["chat"] * e["cost_mult"]}
               for k, e in cfg["llm"]["efforts"].items()}
    providers = []
    from . import local_model
    if local_model.available(cfg["llm"]):
        providers.append({"id": "builtin", "label": "Встроенная (без ключа)", "free": True,
                          "cost": COSTS["chat"] * cfg["llm"]["builtin"].get("cost_mult", 1)})
    providers += [{"id": p["id"], "label": p["label"], "free": p["free"],
                   "cost": COSTS["chat"] * p["cost_mult"]}
                  for p in llm.providers() if p["enabled"]]
    return {"models": llm.available_models() if u["is_admin"] else [],
            "default_model": cfg["llm"]["model"], "fast_model": cfg["llm"]["fast_model"],
            "efforts": efforts, "providers": providers,
            "image": cfg["image"], "video": cfg["video"], "queue": job_queue.qsize()}


# ---------- генерация ----------
@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...), u: dict = Depends(current_user)):
    try:
        img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    except Exception:
        raise HTTPException(400, "Это не изображение")
    name = f"upload_{uuid.uuid4().hex[:12]}.png"
    img.save(WS / name)
    store.add_file(name, u["id"], "upload")
    return {"name": name}


@app.post("/api/image")
def make_image(req: ImageReq, u: dict = Depends(current_user)):
    plan = plan_of(u)
    side = plan["max_image_side"]
    if max(req.width, req.height) > side:
        raise HTTPException(403, f"Ваш тариф «{plan['name']}»: фото до {side} px")
    if req.count > plan["max_images"]:
        raise HTTPException(403, f"Ваш тариф «{plan['name']}»: до {plan['max_images']} фото за раз")
    if req.ref_image:
        upload_path(req.ref_image, u)
    return submit(u, "image", req.model_dump(), COSTS["image"] * req.count)


@app.post("/api/video")
def make_video(req: VideoReq, u: dict = Depends(current_user)):
    plan = plan_of(u)
    limit = plan["video_max_seconds"]
    if not limit:
        raise HTTPException(403, f"Видео недоступно в тарифе «{plan['name']}». Активируйте код в кабинете.")
    if req.seconds > limit:
        raise HTTPException(403, f"Ваш тариф «{plan['name']}»: видео до {limit} сек")
    if req.start_image:
        upload_path(req.start_image, u)
    return submit(u, "video", req.model_dump(), COSTS["video_second"] * math.ceil(req.seconds))


@app.get("/api/jobs")
def list_jobs(u: dict = Depends(current_user)):
    mine = (public(j) for j in jobs.values() if j["user_id"] == u["id"])
    return sorted(mine, key=lambda j: -j["created"])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, u: dict = Depends(current_user)):
    job = jobs.get(job_id)
    if job is None or job["user_id"] != u["id"]:
        raise HTTPException(404, "Задача не найдена")
    return public(job)


@app.get("/api/gallery")
def gallery(u: dict = Depends(current_user)):
    return [{"url": f"/files/{f['name']}", "type": f["kind"], "prompt": f["prompt"]}
            for f in store.files(u["id"]) if (OUT / f["name"]).is_file()]


@app.get("/files/{name}")
def get_file(name: str, u: dict = Depends(current_user)):
    path = OUT / Path(name).name
    if store.file_owner(path.name) != u["id"] or not path.is_file():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path)


# ---------- код и ZIP ----------
def project_context(project_id: str | None, u: dict) -> str:
    owner, context = projects.get(project_id or "", (None, ""))
    return context if owner == u["id"] else ""


@app.post("/api/zip")
async def upload_zip(file: UploadFile = File(...), u: dict = Depends(current_user)):
    if not plan_of(u)["zip"]:
        raise HTTPException(403, f"Загрузка ZIP недоступна в тарифе «{plan_of(u)['name']}»")
    pid = uuid.uuid4().hex[:12]
    tmp = WS / f"upload_{pid}.zip"
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        root = safe_extract(tmp, WS / f"project_{pid}", cfg["zip"]["max_total_mb"], cfg["zip"]["max_files"])
    except zipfile.BadZipFile:
        raise HTTPException(400, "Файл повреждён или это не ZIP-архив")
    except (ZipError, OSError) as e:
        raise HTTPException(400, str(e))
    finally:
        tmp.unlink(missing_ok=True)
    projects[pid] = (u["id"], build_context(root, cfg["llm"]["context_chars"]))
    return {"project_id": pid, "name": file.filename, "tree": tree(root)}


def effort_check(req, u: dict) -> tuple[str, str | None, int]:
    """Проверяет доступность уровня усилий по тарифу и считает цену сообщения."""
    plan = plan_of(u)
    eff = cfg["llm"]["efforts"][req.effort]
    if eff["use"] not in plan["chat_modes"]:
        raise HTTPException(403, f"Уровень «{eff['label']}» недоступен в тарифе «{plan['name']}». "
                                 "Подключите тариф Старт или Про.")
    cost = COSTS["chat"] * eff["cost_mult"]
    return req.effort, (req.model if u["is_admin"] else None), cost


@app.post("/api/chat")
def chat(req: ChatReq, u: dict = Depends(current_user)):
    msgs = [{"role": m["role"], "content": m["content"]} for m in req.messages
            if m.get("role") in ("user", "assistant")]
    context = project_context(req.project_id, u)

    if req.engine == "builtin":
        from . import local_model
        if not local_model.available(cfg["llm"]):
            raise HTTPException(400, "Встроенная модель недоступна на этом сервере")
        cost = COSTS["chat"] * cfg["llm"]["builtin"].get("cost_mult", 1)   # бесплатная, но тратит кредиты как защита от спама
        charge(u, cost, "Код · Встроенная")
        system = llm._system(context, req.explain)
        source = local_model.chat_stream(cfg["llm"], msgs, system, llm.effort(req.effort)["num_predict"])
    elif req.engine and req.engine != "local":
        provider = llm.provider(req.engine)
        enabled = {p["id"] for p in llm.providers() if p["enabled"]}
        if provider is None or req.engine not in enabled:
            raise HTTPException(400, "Эта нейросеть недоступна (не задан ключ или неверный id)")
        # Бесплатные модели (free: true) доступны всем; платные — только на платных тарифах.
        if not provider.get("free") and not plan_of(u)["external"]:
            raise HTTPException(403, f"Эта модель недоступна в тарифе «{plan_of(u)['name']}». "
                                     "Подключите тариф Старт или Про.")
        cost = COSTS["chat"] * provider.get("cost_mult", 3)
        charge(u, cost, f"Код · {provider['label']}")
        source = llm.chat_stream_external(provider, msgs, context, req.effort, req.explain)
    else:
        effort, model, cost = effort_check(req, u)
        charge(u, cost, f"Код · {cfg['llm']['efforts'][effort]['label']}")
        source = llm.chat_stream(msgs, model, context, effort, req.explain)

    def stream():
        finished = False
        for piece in source:
            finished = finished or piece.startswith(STATS_MARK)
            yield piece
        if not finished:  # модель не ответила (выключена/нет ключа) — кредиты возвращаем
            store.refund(u["id"], cost, "Возврат: модель не ответила")

    # X-Accel-Buffering отключает буферизацию в прокси — текст идёт на сайт без задержек.
    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/warmup")
def warmup(req: WarmupReq, u: dict = Depends(current_user)):
    """Сайт вызывает это при открытии раздела «Код» и смене уровня — модель грузится заранее."""
    if req.engine == "builtin":
        from . import local_model
        if local_model.available(cfg["llm"]):
            local_model.warmup(cfg["llm"])
        return {"model": "builtin"}
    model = llm.model_for(req.effort, req.model if u["is_admin"] else None)
    llm.warmup(model, project_context(req.project_id, u))
    return {"model": model}


@app.post("/api/export")
def export(req: ExportReq, u: dict = Depends(current_user)):
    data = code_blocks_to_zip(req.text)
    if not data:
        raise HTTPException(400, "В ответах нет блоков кода")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="arturokai_code.zip"'})


# ---------- администратор ----------
@app.post("/api/admin/codes")
def admin_new_codes(req: NewCodesReq, _: dict = Depends(admin_user)):
    try:
        codes = store.create_codes(req.kind, req.count, req.plan, req.days, req.credits, req.note)
    except StoreError as e:
        raise HTTPException(400, str(e))
    return {"codes": codes}


@app.get("/api/admin/codes")
def admin_codes(_: dict = Depends(admin_user)):
    return store.list_codes()


@app.get("/api/admin/codes.csv")
def admin_codes_csv(only_free: bool = False, _: dict = Depends(admin_user)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Код", "Тип", "Тариф", "Дней", "Кредитов", "Заметка", "Активировал"])
    for c in store.list_codes(limit=100_000):
        if only_free and c["used_by"]:
            continue
        kind = "Подписка" if c["kind"] == "plan" else "Пакет генераций"
        plan = PLANS[c["plan"]]["name"] if c["plan"] in PLANS else ""
        w.writerow([c["code"], kind, plan, c["days"] or "", c["credits"], c["note"], c["used_login"] or ""])
    # BOM — чтобы Excel правильно показал русские буквы.
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="arturokai_codes.csv"'})


@app.get("/api/admin/users")
def admin_users(_: dict = Depends(admin_user)):
    return store.list_users()


@app.get("/api/admin/pricing")
def admin_get_pricing(_: dict = Depends(admin_user)):
    return store.get_pricing()


@app.post("/api/admin/pricing")
def admin_set_pricing(req: PricingReq, _: dict = Depends(admin_user)):
    # Цены меняются «на месте» в общих словарях — все пользователи сразу видят новые.
    store.set_pricing(req.model_dump())
    return store.get_pricing()


# ---------- таблицы с автоподсчётом ----------
@app.get("/api/sheets")
def list_sheets(u: dict = Depends(current_user)):
    return store.list_sheets(u["id"])


@app.get("/api/sheets/{sheet_id}")
def get_sheet(sheet_id: int, u: dict = Depends(current_user)):
    sheet = store.get_sheet(sheet_id, u["id"])
    if sheet is None:
        raise HTTPException(404, "Таблица не найдена")
    return sheet


@app.post("/api/sheets")
def create_sheet(req: SheetReq, u: dict = Depends(current_user)):
    return store.create_sheet(u["id"], req.name, req.rows, req.cols)


@app.put("/api/sheets/{sheet_id}")
def save_sheet(sheet_id: int, req: SheetReq, u: dict = Depends(current_user)):
    try:
        return store.save_sheet(sheet_id, u["id"], req.name, req.rows, req.cols, req.data)
    except StoreError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/sheets/{sheet_id}")
def delete_sheet(sheet_id: int, u: dict = Depends(current_user)):
    store.delete_sheet(sheet_id, u["id"])
    return {"ok": True}


# ---------- страницы и установка как приложение (PWA) ----------
app.mount("/static", StaticFiles(directory=WEB), name="static")

# Эти файлы должны лежать в корне сайта, чтобы установка работала на всех устройствах.
_ROOT_FILES = {
    "manifest.webmanifest": "application/manifest+json",
    "icon-192.png": "image/png", "icon-512.png": "image/png",
    "icon-maskable.png": "image/png", "apple-touch-icon.png": "image/png",
}
for _name, _type in _ROOT_FILES.items():
    app.add_api_route(f"/{_name}", (lambda n=_name, t=_type: FileResponse(WEB / n, media_type=t)),
                      methods=["GET"], include_in_schema=False)


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Service-Worker-Allowed: / разрешает воркеру работать для всего сайта.
    return FileResponse(WEB / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


def main():
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 — открыть сайт в локальной сети")
    ap.add_argument("--port", type=int, default=7860)
    args = ap.parse_args()
    ensure_admin()
    print(f"ARTurokAI: http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
