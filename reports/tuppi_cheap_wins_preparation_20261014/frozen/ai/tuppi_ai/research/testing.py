"""Small helpers shared by tests/research (fixture loading, native observations)."""

from __future__ import annotations


def fixture_case(fid: str, index: int = 0):
    from .fixtures import load_fixture

    payload, cases, truth = load_fixture(fid)
    if payload["status"] != "VALIDATED":
        raise AssertionError(f"{fid} is {payload['status']}")
    return cases[index], truth


def tobs_of(case):
    from ..bridge import obs_from_player_observation

    return obs_from_player_observation(case.policy_observation())
