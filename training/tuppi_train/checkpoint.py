"""Resumable training state on a disk that may vanish mid-write (Google Drive).

Two slots are written alternately, each by write-to-temporary, fsync, rename. A
write that is cut off leaves the temporary file behind and both slots as they
were; a slot that cannot be read is skipped on load. So the newest complete
state is always recoverable and at most one save interval of work is lost.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import torch

FORMAT = "tuppi.train.vrpo.v1"
SLOTS = ("state_a.pt", "state_b.pt")


def atomic_save(obj, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        torch.save(obj, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Rotating:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.next = 0

    def load(self) -> dict | None:
        """The newest readable state, or None. The next save goes to the other slot."""
        best, best_slot = None, -1
        for i, name in enumerate(SLOTS):
            path = self.dir / name
            if not path.exists():
                continue
            try:
                state = torch.load(path, map_location="cpu", weights_only=False)
            except Exception as error:  # truncated or corrupt: fall back to the other slot
                print(f"checkpoint {path} unreadable ({type(error).__name__}); skipped", flush=True)
                continue
            if state.get("format") != FORMAT:
                continue
            if best is None or (state["iteration"], state["saved_at"]) > (best["iteration"], best["saved_at"]):
                best, best_slot = state, i
        if best is not None:
            self.next = 1 - best_slot
        return best

    def save(self, state: dict) -> Path:
        state = {**state, "format": FORMAT, "saved_at": time.time()}
        path = self.dir / SLOTS[self.next]
        atomic_save(state, path)
        self.next = 1 - self.next
        return path
