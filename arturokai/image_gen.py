import inspect
import time
import uuid
from pathlib import Path

import torch
from diffusers import AutoPipelineForImage2Image, AutoPipelineForText2Image
from PIL import Image

from .devices import pick_device, place


class ImageGenerator:
    def __init__(self, cfg: dict, output_dir: Path):
        self.cfg = cfg
        self.output_dir = output_dir
        self.pipe = None
        self.img2img = None

    def _load(self):
        if self.pipe is None:
            _, dtype = pick_device()
            pipe = AutoPipelineForText2Image.from_pretrained(self.cfg["model"], torch_dtype=dtype)
            self.pipe = place(pipe, self.cfg.get("cpu_offload", "auto"))
        return self.pipe

    def _load_img2img(self):
        if self.img2img is None:
            # Те же веса, что и для генерации по описанию — модель не грузится второй раз.
            self.img2img = AutoPipelineForImage2Image.from_pipe(self._load())
        return self.img2img

    def generate(self, prompt: str, negative: str = "", width=None, height=None,
                 steps=None, seed: int = -1, count: int = 1,
                 ref_image: Image.Image | None = None, strength: float = 0.6) -> list[Path]:
        """Фото по описанию, а если передан ref_image — по примеру фото и описанию.

        strength: насколько сильно менять пример (0.1 — почти копия, 0.95 — только идея).
        """
        seed = seed if seed >= 0 else int(time.time()) % 2**31
        width, height = int(width or self.cfg["width"]), int(height or self.cfg["height"])
        steps = int(steps or self.cfg["steps"])
        kwargs = dict(prompt=prompt, width=width, height=height)
        if ref_image is None:
            pipe = self._load()
        else:
            pipe = self._load_img2img()
            kwargs["image"] = ref_image.convert("RGB").resize((width, height))
            kwargs["strength"] = float(strength)
            # Модель делает только steps * strength шагов — хотя бы один должен остаться.
            steps = max(steps, int(1 / float(strength)) + 1)
        kwargs.update(
            num_inference_steps=steps,
            guidance_scale=float(self.cfg["guidance"]),
            num_images_per_prompt=int(count),
            generator=torch.Generator("cpu").manual_seed(seed),
        )
        # FLUX не принимает negative_prompt, SDXL — принимает.
        if negative and "negative_prompt" in inspect.signature(pipe.__call__).parameters:
            kwargs["negative_prompt"] = negative
        images = pipe(**kwargs).images
        paths = []
        for i, img in enumerate(images):
            p = self.output_dir / f"img_{seed}_{uuid.uuid4().hex[:6]}_{i}.png"
            img.save(p)
            paths.append(p)
        return paths
