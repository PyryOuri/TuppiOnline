from __future__ import annotations

from pathlib import Path

from hypothesis import settings


ROOT = Path(__file__).resolve().parents[3]

settings.register_profile(
    "project_target_v1",
    max_examples=100,
    derandomize=True,
    database=None,
    deadline=None,
)
settings.load_profile("project_target_v1")
