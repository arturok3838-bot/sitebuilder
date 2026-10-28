"""Веб-интерфейс ARTurokAI. Запуск: python -m arturokai.app  →  http://127.0.0.1:7860"""
import argparse
import time

import gradio as gr

from .config import load_config
from .llm import LocalLLM
from .zip_tools import ZipError, build_context, code_blocks_to_zip, safe_extract, tree

cfg = load_config()
OUT, WS = cfg["output_dir"], cfg["workspace_dir"]
llm = LocalLLM(cfg["llm"])
_image_gen = _video_gen = None


def image_gen():
    global _image_gen
    if _image_gen is None:
        from .image_gen import ImageGenerator  # torch грузится только при первом использовании
        _image_gen = ImageGenerator(cfg["image"], OUT)
    return _image_gen


def video_gen():
    global _video_gen
    if _video_gen is None:
        from .video_gen import VideoGenerator
        _video_gen = VideoGenerator(cfg["video"], OUT)
    return _video_gen


def do_image(prompt, negative, width, height, steps, seed, count):
    if not prompt.strip():
        raise gr.Error("Введите описание картинки")
    return [str(p) for p in image_gen().generate(prompt, negative, width, height, steps, int(seed), int(count))]


def do_video(prompt, negative, seconds, start_image, steps, seed, progress=gr.Progress()):
    if not prompt.strip():
        raise gr.Error("Введите описание видео")
    return str(video_gen().generate(prompt, seconds, negative, start_image, int(seed), steps, progress))


def do_zip(file):
    if file is None:
        return "", "Архив не загружен"
    try:
        root = safe_extract(file, WS / "project", cfg["zip"]["max_total_mb"], cfg["zip"]["max_files"])
    except (ZipError, OSError) as e:
        raise gr.Error(str(e))
    ctx = build_context(root, cfg["llm"]["context_chars"])
    return ctx, f"Распаковано в {root}\n\n{tree(root)}"


def do_chat(message, history, model, context):
    history = history + [{"role": "user", "content": message}]
    yield history + [{"role": "assistant", "content": "…"}], ""
    answer = ""
    msgs = [{"role": m["role"], "content": m["content"]} for m in history]
    for piece in llm.chat_stream(msgs, model or None, context):
        answer += piece
        yield history + [{"role": "assistant", "content": answer}], ""


def do_export(history):
    text = "\n".join(m["content"] for m in history or [] if m["role"] == "assistant")
    data = code_blocks_to_zip(text)
    if not data:
        raise gr.Error("В ответах нет блоков кода")
    path = OUT / f"code_{int(time.time())}.zip"
    path.write_bytes(data)
    return str(path)


def build_ui() -> gr.Blocks:
    v = cfg["video"]
    with gr.Blocks(title="ARTurokAI") as ui:
        gr.Markdown("# ARTurokAI\nЛичная локальная нейросеть: фото, видео до 2 минут, код и ZIP.")

        with gr.Tab("🖼 Фото"):
            with gr.Row():
                with gr.Column():
                    p = gr.Textbox(label="Описание", lines=4)
                    n = gr.Textbox(label="Чего не должно быть (для SDXL)")
                    with gr.Row():
                        w = gr.Slider(512, 2048, cfg["image"]["width"], step=64, label="Ширина")
                        h = gr.Slider(512, 2048, cfg["image"]["height"], step=64, label="Высота")
                    with gr.Row():
                        st = gr.Slider(1, 60, cfg["image"]["steps"], step=1, label="Шаги")
                        sd = gr.Number(-1, label="Seed (-1 = случайный)", precision=0)
                        cnt = gr.Slider(1, 4, 1, step=1, label="Количество")
                    b = gr.Button("Создать", variant="primary")
                gal = gr.Gallery(label="Результат", columns=2)
            b.click(do_image, [p, n, w, h, st, sd, cnt], gal)

        with gr.Tab("🎬 Видео"):
            with gr.Row():
                with gr.Column():
                    vp = gr.Textbox(label="Описание сцены", lines=4)
                    vn = gr.Textbox(label="Чего не должно быть")
                    secs = gr.Slider(1, v["max_seconds"], 5, step=1, label="Длительность, сек (до 120)")
                    img = gr.Image(label="Стартовый кадр (необязательно)", type="pil")
                    with gr.Row():
                        vst = gr.Slider(10, 60, v["steps"], step=1, label="Шаги")
                        vsd = gr.Number(-1, label="Seed", precision=0)
                    vb = gr.Button("Создать видео", variant="primary")
                vid = gr.Video(label="Результат")
            vb.click(do_video, [vp, vn, secs, img, vst, vsd], vid)

        with gr.Tab("💻 Код и ZIP"):
            context = gr.State("")
            with gr.Row():
                with gr.Column(scale=1):
                    zf = gr.File(label="ZIP-архив проекта", file_types=[".zip"], type="filepath")
                    info = gr.Textbox(label="Содержимое", lines=14)
                    models = llm.available_models()
                    mdl = gr.Dropdown(models or [cfg["llm"]["model"]], value=cfg["llm"]["model"],
                                      allow_custom_value=True, label="Модель Ollama")
                    exp = gr.Button("Скачать код из ответов как ZIP")
                    zout = gr.File(label="Готовый ZIP")
                with gr.Column(scale=2):
                    chat = gr.Chatbot(height=600, label="ARTurokAI")
                    msg = gr.Textbox(placeholder="Напишите задачу… (Enter — отправить)", lines=2)
                    clr = gr.Button("Очистить чат")
            zf.change(do_zip, zf, [context, info])
            msg.submit(do_chat, [msg, chat, mdl, context], [chat, msg])
            clr.click(lambda: [], None, chat)
            exp.click(do_export, chat, zout)
    return ui


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 — открыть доступ в локальной сети")
    ap.add_argument("--port", type=int, default=7860)
    args = ap.parse_args()
    build_ui().queue().launch(server_name=args.host, server_port=args.port, allowed_paths=[str(OUT)])


if __name__ == "__main__":
    main()
