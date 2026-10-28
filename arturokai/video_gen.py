"""Видео до 2 минут.

Модели вроде Wan генерируют ~5 секунд за проход, поэтому длинный ролик
собирается из сегментов: последний кадр сегмента становится стартовой
картинкой следующего (image-to-video), так сцена продолжается без склеек.
Кадры пишутся в файл потоково, чтобы 2 минуты видео не держать в памяти.
"""
import math
import time
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import torch
from diffusers import WanImageToVideoPipeline, WanPipeline
from PIL import Image

from .devices import pick_device, place


def segments_needed(seconds: float, fps: int, frames_per_segment: int) -> int:
    """Сколько сегментов нужно; у каждого следующего первый кадр — дубль, он отбрасывается."""
    total = max(1, round(seconds * fps))
    if total <= frames_per_segment:
        return 1
    return 1 + math.ceil((total - frames_per_segment) / (frames_per_segment - 1))


def _to_uint8(frame) -> np.ndarray:
    if isinstance(frame, Image.Image):
        return np.asarray(frame.convert("RGB"))
    arr = np.asarray(frame)
    if arr.dtype != np.uint8:
        arr = (np.clip(arr, 0, 1) * 255).round().astype(np.uint8)
    return arr


class VideoGenerator:
    def __init__(self, cfg: dict, output_dir: Path):
        self.cfg = cfg
        self.output_dir = output_dir
        self.t2v = None
        self.i2v = None

    def _load_t2v(self):
        if self.t2v is None:
            _, dtype = pick_device()
            pipe = WanPipeline.from_pretrained(self.cfg["t2v_model"], torch_dtype=dtype)
            self.t2v = place(pipe, self.cfg.get("cpu_offload", True))
        return self.t2v

    def _load_i2v(self):
        if self.i2v is None:
            _, dtype = pick_device()
            if self.t2v is not None and self.cfg["i2v_model"] == self.cfg["t2v_model"]:
                # Те же веса — переиспользуем компоненты, не грузим модель второй раз.
                pipe = WanImageToVideoPipeline(**self.t2v.components)
            else:
                pipe = WanImageToVideoPipeline.from_pretrained(self.cfg["i2v_model"], torch_dtype=dtype)
                pipe = place(pipe, self.cfg.get("cpu_offload", True))
            self.i2v = pipe
        return self.i2v

    def generate(self, prompt: str, seconds: float, negative: str = "",
                 start_image: Image.Image | None = None, seed: int = -1,
                 steps=None, progress=None) -> Path:
        cfg = self.cfg
        seconds = min(float(seconds), float(cfg["max_seconds"]))
        fps, fps_seg = int(cfg["fps"]), int(cfg["frames_per_segment"])
        w, h = int(cfg["width"]), int(cfg["height"])
        total_frames = max(1, round(seconds * fps))
        n_seg = segments_needed(seconds, fps, fps_seg)
        seed = seed if seed >= 0 else int(time.time()) % 2**31
        out = self.output_dir / f"video_{seed}.mp4"

        common = dict(prompt=prompt, negative_prompt=negative or None, height=h, width=w,
                      num_frames=fps_seg, num_inference_steps=int(steps or cfg["steps"]),
                      guidance_scale=float(cfg["guidance"]), output_type="np")

        written = 0
        last = start_image.convert("RGB").resize((w, h)) if start_image else None
        with imageio.get_writer(out, fps=fps, codec="libx264", quality=8,
                                macro_block_size=16) as writer:
            for i in range(n_seg):
                if progress:
                    progress(i / n_seg, desc=f"Сегмент {i + 1}/{n_seg}")
                gen = torch.Generator("cpu").manual_seed(seed + i)
                if last is None:
                    frames = self._load_t2v()(generator=gen, **common).frames[0]
                else:
                    frames = self._load_i2v()(image=last, generator=gen, **common).frames[0]
                # Первый кадр продолжения совпадает с последним кадром прошлого сегмента.
                start = 1 if i > 0 else 0
                for f in frames[start:]:
                    if written >= total_frames:
                        break
                    writer.append_data(_to_uint8(f))
                    written += 1
                last = Image.fromarray(_to_uint8(frames[-1]))
        if progress:
            progress(1.0, desc="Готово")
        return out
