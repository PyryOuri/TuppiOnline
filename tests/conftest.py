"""Keeps the research contract tests (tests/research) out of the default run.

tests/research binds tuppi_ai.native to the research build for its whole
process, so it must never share a pytest session with the existing tests.
It runs only when asked for explicitly:

    ~/.venvs/tuppi-v2/bin/python -m pytest tests/research -q
"""

from pathlib import Path

_RESEARCH = (Path(__file__).parent / "research").resolve()


def pytest_ignore_collect(collection_path, config):
    if Path(collection_path).resolve() != _RESEARCH:
        return None
    requested = [Path(str(a).split("::")[0]).resolve() for a in config.args]
    if any(a == _RESEARCH or _RESEARCH in a.parents for a in requested):
        return None
    return True
