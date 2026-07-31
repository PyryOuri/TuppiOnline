from __future__ import annotations

import pytest

from tuppi_legacy.legacy_loader import load_legacy_module


@pytest.fixture(scope="session")
def legacy():
    return load_legacy_module()

