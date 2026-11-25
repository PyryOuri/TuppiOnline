"""Device selection for training: CUDA, then Apple MPS, then the CPU."""

from __future__ import annotations

import os

import torch


#: Config.amp -> the autocast dtype of the network forward passes (None = plain float32).
AMP = {"off": None, "bf16": torch.bfloat16, "fp16": torch.float16}


def pick(name: str | None = None) -> torch.device:
    name = name or os.environ.get("TUPPI_DEVICE")
    if name:
        return torch.device(name)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def setup(dev: torch.device, tf32: bool = True) -> None:
    """TF32 matrix products on CUDA (faster on Ampere and later GPUs, about three decimal
    digits in each product). The rollout sampler and the learner run the same network code
    under the same setting, so behaviour and recomputed log-probabilities agree either way;
    `python -m tuppi_train.check` measures that on the device."""
    if dev.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = tf32
        torch.backends.cudnn.allow_tf32 = tf32


def adamw(params, lr: float, weight_decay: float, dev: torch.device) -> torch.optim.AdamW:
    return torch.optim.AdamW(params, lr=lr, weight_decay=weight_decay, fused=dev.type in ("cuda", "mps"))


def generator(dev: torch.device, seed: int):
    """A generator on the device for the rollout sampler, or None where the backend has none."""
    try:
        return torch.Generator(device=dev).manual_seed(seed)
    except RuntimeError:
        return None


def describe(dev: torch.device) -> dict:
    info = {"device": str(dev), "torch": torch.__version__, "cpus": os.cpu_count()}
    try:
        info["cpus_usable"] = len(os.sched_getaffinity(0))
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        info["ram_gb"] = round(pages * size / 2**30, 1)
    except (AttributeError, ValueError, OSError):
        pass
    if dev.type == "cuda":
        p = torch.cuda.get_device_properties(dev)
        info.update(gpu=p.name, vram_gb=round(p.total_memory / 2**30, 1))
    return info
