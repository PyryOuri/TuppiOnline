"""Contract tests for tuppi_ai.research (acceptance IDs in the test names/docstrings).

This process runs the UNMODIFIED tuppi_ai code on the R0-parity research
build (bound before anything imports tuppi_ai.native), which the three-library
parity report (builds/parity_report.json, A03) shows is bitwise identical to
the installed library on the probe set. Run these tests on their own:

    ~/.venvs/tuppi-v2/bin/python -m pytest tests/research -q

Workload stays inside the contract caps: fixtures are loaded from the
validated fixture files, runner tests use cheap policies on fixture decks,
and at most two complete search-played deals run (A06 and R02).
"""

from __future__ import annotations

import ctypes as C
import sys

import pytest

from tuppi_ai.research.native_api import RESEARCH_LIB, bind_native

if not RESEARCH_LIB.exists():
    pytest.exit("research build missing: run native/research/build_research.sh", returncode=4)
if "tuppi_ai.native" in sys.modules:
    pytest.exit("tuppi_ai.native was imported before the research tests could bind R0-parity; "
                "run tests/research on its own", returncode=4)
bind_native(RESEARCH_LIB)


@pytest.fixture(scope="session")
def research():
    from tuppi_ai.research.native_api import ResearchLibrary

    return ResearchLibrary()


@pytest.fixture(scope="session")
def nat():
    import tuppi_ai.native as nat

    return nat


@pytest.fixture(scope="session")
def net():
    from tuppi_ai.research.clone_policy import rollout_network

    return rollout_network()


@pytest.fixture(scope="session")
def table():
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity

    return Equity.load(EQUITY).table


@pytest.fixture(scope="session")
def mlp(nat, net):
    return nat.Mlp(net)


@pytest.fixture()
def search_env(nat, table, net):
    """An environment configured exactly as a best Searcher's (W128 x 26 slots)."""
    return nat.Env(128 * 26, 0, table, single_deal=True, encoder=net.encoder)


from tuppi_ai.research.testing import fixture_case, tobs_of  # noqa: E402,F401


@pytest.fixture(scope="session")
def f02():
    return fixture_case("F02", 0)


@pytest.fixture(scope="session")
def f02b():
    return fixture_case("F02", 1)



def u64(x: int) -> C.c_uint64:
    return C.c_uint64(x)
