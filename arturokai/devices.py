import torch


def pick_device() -> tuple[str, torch.dtype]:
    if torch.cuda.is_available():
        return "cuda", torch.bfloat16
    if torch.backends.mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32


def place(pipe, cpu_offload: bool):
    """Переносит пайплайн на GPU или включает выгрузку в ОЗУ для экономии VRAM."""
    device, _ = pick_device()
    if device == "cuda" and cpu_offload:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(device)
    return pipe
