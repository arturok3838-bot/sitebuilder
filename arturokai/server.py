"""Сайт ARTurokAI. Запуск: python -m arturokai.server  →  http://127.0.0.1:7860

Генерация фото и видео идёт через очередь задач: видеокарта одна, поэтому задачи
выполняются по очереди в фоновом потоке, а сайт опрашивает их прогресс.
"""
import argparse
import io
import queue
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from .config import ROOT, load_config
from .llm import LocalLLM
from .zip_tools import ZipError, build_context, code_blocks_to_zip, safe_extract, tree

cfg = load_config()
OUT, WS = cfg["output_dir"], cfg["workspace_dir"]
WEB = ROOT / "web"
llm = LocalLLM(cfg["llm"])

app = FastAPI(title="ARTurokAI")
jobs: dict[str, dict] = {}
job_queue: queue.Queue = queue.Queue()
projects: dict[str, str] = {}   # id ZIP-проекта -> текстовый контекст для модели
_gens: dict = {}


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


def url(path: Path) -> str:
    return f"/outputs/{path.name}"


def run_job(job: dict):
    p = job["params"]

    def progress(frac, desc=""):
        job["progress"], job["desc"] = float(frac), desc

    if job["kind"] == "image":
        job["desc"] = "Загрузка модели и генерация…"
        paths = generator("image").generate(p["prompt"], p["negative"], p["width"], p["height"],
                                            p["steps"], p["seed"], p["count"])
        job["result"] = [url(x) for x in paths]
    else:
        start = None
        if p.get("start_image"):
            start = Image.open(WS / p["start_image"])
        path = generator("video").generate(p["prompt"], p["seconds"], p["negative"], start,
                                           p["seed"], p["steps"], progress)
        job["result"] = [url(path)]


def worker():
    while True:
        job = job_queue.get()
        job["status"], job["started"] = "running", time.time()
        try:
            run_job(job)
            job["status"], job["progress"] = "done", 1.0
        except Exception as e:  # ошибку показываем на сайте, очередь продолжает работать
            job["status"], job["error"] = "error", str(e)
        job["finished"] = time.time()


threading.Thread(target=worker, daemon=True).start()
if cfg["llm"].get("preload"):
    llm.warmup(cfg["llm"]["fast_model"])


def submit(kind: str, params: dict) -> dict:
    job = dict(id=uuid.uuid4().hex[:12], kind=kind, params=params, status="queued",
               progress=0.0, desc="В очереди", result=[], error=None, created=time.time())
    jobs[job["id"]] = job
    job_queue.put(job)
    return public(job)


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "params"} | {"prompt": job["params"]["prompt"]}


class ImageReq(BaseModel):
    prompt: str = Field(min_length=1)
    negative: str = ""
    width: int = Field(cfg["image"]["width"], ge=256, le=2048)
    height: int = Field(cfg["image"]["height"], ge=256, le=2048)
    steps: int = Field(cfg["image"]["steps"], ge=1, le=100)
    seed: int = -1
    count: int = Field(1, ge=1, le=4)


class VideoReq(BaseModel):
    prompt: str = Field(min_length=1)
    negative: str = ""
    seconds: float = Field(5, ge=1, le=cfg["video"]["max_seconds"])
    steps: int = Field(cfg["video"]["steps"], ge=5, le=100)
    seed: int = -1
    start_image: str | None = None   # имя файла, полученное от /api/upload-image


class ChatReq(BaseModel):
    messages: list[dict]
    model: str | None = None          # явный выбор модели; иначе — по режиму
    mode: Literal["fast", "precise"] = "fast"
    project_id: str | None = None


class WarmupReq(BaseModel):
    model: str | None = None
    mode: Literal["fast", "precise"] = "fast"
    project_id: str | None = None


class ExportReq(BaseModel):
    text: str


@app.get("/api/status")
def status():
    return {"models": llm.available_models(), "default_model": cfg["llm"]["model"],
            "fast_model": cfg["llm"]["fast_model"],
            "image": cfg["image"], "video": cfg["video"], "queue": job_queue.qsize()}


@app.post("/api/image")
def make_image(req: ImageReq):
    return submit("image", req.model_dump())


@app.post("/api/video")
def make_video(req: VideoReq):
    if req.start_image and not (WS / req.start_image).is_file():
        raise HTTPException(400, "Стартовый кадр не найден, загрузите его заново")
    return submit("video", req.model_dump())


@app.post("/api/upload-image")
async def upload_image(file: UploadFile = File(...)):
    try:
        img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    except Exception:
        raise HTTPException(400, "Это не изображение")
    name = f"start_{uuid.uuid4().hex[:8]}.png"
    img.save(WS / name)
    return {"name": name}


@app.get("/api/jobs")
def list_jobs():
    return sorted((public(j) for j in jobs.values()), key=lambda j: -j["created"])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Задача не найдена")
    return public(jobs[job_id])


@app.get("/api/gallery")
def gallery():
    files = [p for p in OUT.iterdir() if p.suffix in (".png", ".mp4")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"url": url(p), "type": "video" if p.suffix == ".mp4" else "image"} for p in files[:200]]


@app.post("/api/zip")
async def upload_zip(file: UploadFile = File(...)):
    pid = uuid.uuid4().hex[:8]
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
    projects[pid] = build_context(root, cfg["llm"]["context_chars"])
    return {"project_id": pid, "name": file.filename, "tree": tree(root)}


@app.post("/api/chat")
def chat(req: ChatReq):
    context = projects.get(req.project_id or "", "")
    msgs = [{"role": m["role"], "content": m["content"]} for m in req.messages
            if m.get("role") in ("user", "assistant")]
    stream = llm.chat_stream(msgs, req.model, context, req.mode)
    # X-Accel-Buffering отключает буферизацию в прокси — текст идёт на сайт без задержек.
    return StreamingResponse(stream, media_type="text/plain; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/warmup")
def warmup(req: WarmupReq):
    """Сайт вызывает это при открытии раздела «Код» и смене режима — модель грузится заранее."""
    model = llm.model_for(req.mode, req.model)
    llm.warmup(model, projects.get(req.project_id or "", ""))
    return {"model": model}


@app.post("/api/export")
def export(req: ExportReq):
    data = code_blocks_to_zip(req.text)
    if not data:
        raise HTTPException(400, "В ответах нет блоков кода")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="arturokai_code.zip"'})


app.mount("/outputs", StaticFiles(directory=OUT), name="outputs")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


def main():
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 — открыть сайт в локальной сети")
    ap.add_argument("--port", type=int, default=7860)
    args = ap.parse_args()
    print(f"ARTurokAI: http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
