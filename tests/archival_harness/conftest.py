from __future__ import annotations

from pathlib import Path

import pytest

from tuppi_legacy.adapter import RunnerConfig
from tuppi_legacy.deals import load_deals

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def example_deal():
    return load_deals(ROOT / "examples/legacy_deal_seed_1729.json")[0]


@pytest.fixture
def runner_config():
    return RunnerConfig(
        deal_count=1,
        legacy_rng_seed=2718,
        rollouts=1,
        scoring="rising",
        show_banned_ranks=(2, 11, 12, 13),
    )

