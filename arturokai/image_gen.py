import inspect
import time
from pathlib import Path

import torch
from diffusers import AutoPipelineForText2Image

from .devices import pick_device, place


class ImageGenerator:
    def __init__(self, cfg: dict, output_dir: Path):
        self.cfg = cfg
        self.output_dir = output_dir
        self.pipe = None

    def _load(self):
        if self.pipe is None:
            _, dtype = pick_device()
            pipe = AutoPipelineForText2Image.from_pretrained(self.cfg["model"], torch_dtype=dtype)
            self.pipe = place(pipe, self.cfg.get("cpu_offload", "auto"))
        return self.pipe

    def generate(self, prompt: str, negative: str = "", width=None, height=None,
                 steps=None, seed: int = -1, count: int = 1) -> list[Path]:
        pipe = self._load()
        seed = seed if seed >= 0 else int(time.time()) % 2**31
        kwargs = dict(
            prompt=prompt,
            width=int(width or self.cfg["width"]),
            height=int(height or self.cfg["height"]),
            num_inference_steps=int(steps or self.cfg["steps"]),
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
            p = self.output_dir / f"img_{seed}_{i}.png"
            img.save(p)
            paths.append(p)
        return paths
