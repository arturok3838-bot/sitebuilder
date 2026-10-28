import torch

if torch.cuda.is_available():
    # TF32 и автоподбор свёрток заметно ускоряют генерацию на картах NVIDIA RTX.
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = True


def pick_device() -> tuple[str, torch.dtype]:
    if torch.cuda.is_available():
        return "cuda", torch.bfloat16
    if torch.backends.mps.is_available():
        return "mps", torch.float16
    return "cpu", torch.float32


def place(pipe, cpu_offload: bool | str = "auto"):
    """Ставит пайплайн на видеокарту.

    cpu_offload: false — всё на GPU (быстрее всего); true — части модели держатся
    в ОЗУ (меньше VRAM, медленнее); "auto" — на GPU, а при нехватке памяти выгрузка.
    """
    device, _ = pick_device()
    if device != "cuda":
        return pipe.to(device)
    if cpu_offload is True:
        pipe.enable_model_cpu_offload()
        return pipe
    try:
        return pipe.to("cuda")
    except torch.cuda.OutOfMemoryError:
        if cpu_offload is False:
            raise
        pipe.to("cpu")
        torch.cuda.empty_cache()
        pipe.enable_model_cpu_offload()
        return pipe
