"""C3a contract tests K05-K09: mode-state sufficiency evidence and the pure kernel solver."""

from __future__ import annotations

import ctypes as C
import re
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from tuppi_ai.research import c3_kernel as K
from tuppi_ai.research.ledger import count
from tuppi_ai.research.lifecycle import ModeTracker
from tuppi_ai.research.testing import fixture_case, tobs_of

AI = Path(__file__).resolve().parents[2]

#: Every call site that can write a native environment's sooli settings (outside tuppi_ai/research).
KNOWN_SETTERS = {
    ("tuppi_ai/search.py", 'env.set_sooli(cfg["belief"], False, cfg["offer_play_heur"], cfg["lam"])'),  # offer -> O
    ("tuppi_ai/search.py", 'env.set_sooli(cfg["belief"], False, False, cfg["lam"])'),                 # give/play -> P
    ("tuppi_ai/search.py", 'sr.env.set_sooli(cfg["belief"], False, cfg["offer_play_heur"], cfg["lam"])'),  # v2 only
    ("tuppi_ai/review.py", 'self.env.set_sooli(cfg["belief"], False, False if in_sooli else cfg["offer_play_heur"], cfg["lam"])'),
    ("tuppi_ai/rule_bidder.py", 'agent.searcher.env.set_sooli(cfg["belief"], False, cfg["offer_play_heur"], cfg["lam"])'),
    ("tools/gen_game_db.py", "searcher.env.set_sooli(0, False, False, 0.0)"),
    ("tools/profile_search.py", "searcher.env.set_sooli(0, False, False, 0.0)"),  # per-deal reset, as gen_game_db
    ("tools/sooli_play_eval.py", 'env.set_sooli(int(o.get("b", 1)), False, bool(int(o.get("ph", 0))), float(o.get("l", 0.0)))'),
    ("tools/sooli_bank.py", '_W["env"].set_sooli(1, False, play_heur)'),
    # 2026-09-30 merge of sp/selfplay: cold settings on self-play, value-net and diagnostic environments
    ("tuppi_ai/branch_eval.py", "sr.env.set_sooli(0, False, False, 0.0)"),
    ("tuppi_ai/selfplay.py", "env.set_sooli(0, False, False, 0.0)"),
    ("tuppi_ai/value.py", "env.set_sooli(0, False, False, 0.0)"),
    ("tuppi_ai/vrpo.py", "env.set_sooli(0, False, False, 0.0)"),
    ("tools/dd_consensus.py", "env.set_sooli(0, False, False, 0.0)"),
    ("tools/gen_value_games.py", "agent.searcher.env.set_sooli(0, False, False, 0.0)"),
    ("tools/distil_policy.py", "env.set_sooli(0, False, False, 0.0)"),
    ("tools/distil_policy.py", "env_eval.set_sooli(0, False, False, 0.0)"),
    ("tools/heuristic_mining.py", '_W["env"].set_sooli(0, False, False, 0.0)'),
}


def test_K05_setter_inventory_is_complete():
    found = set()
    for sub in ("tuppi_ai", "tools"):
        for path in (AI / sub).rglob("*.py"):
            rel = str(path.relative_to(AI))
            if rel.startswith("tuppi_ai/research/"):
                continue
            for line in path.read_text().splitlines():
                if re.search(r"\.set_sooli\(", line) and "def set_sooli" not in line:
                    found.add((rel, line.strip()))
    assert found == KNOWN_SETTERS, found ^ KNOWN_SETTERS


def test_K05_fresh_environment_is_cold_and_tracker_covers_every_branch(research, nat):
    env = nat.Env(8, 0, encoder=2)
    cfg = research.env_config(env)
    assert (cfg["sooli_belief"], cfg["sooli_return_pi"], cfg["sooli_play_heur"], cfg["sooli_lambda"]) == (0, 0, 0, 0.0)

    class O:  # minimal observation stand-in for the tracker
        def __init__(self, phase, ruleset="project_target_v3"):
            from tuppi_engine.state import EnginePhase
            from tuppi_rules import RulesetId
            self.phase, self.ruleset_id = EnginePhase(phase), RulesetId(ruleset)

    from tuppi_ai.search import SOOLI_DEFAULTS
    t = ModeTracker()
    seq = [("SHOWING", 5, "C"), ("TRICK_PLAY", 3, "C"), ("SOOLI_OFFER", 2, "O"), ("SOOLI_GIVE", 13, "P"),
           ("SOOLI_PLAY", 1, "P"), ("SOOLI_RETURN", 13, "P"), ("SOOLI_OFFER", 2, "O"), ("SOOLI_RETURN", 13, "O"),
           ("SHOWING", 4, "O"), ("SOOLI_PLAY", 3, "P")]
    for phase, n, want in seq:
        assert t.observe_call(O(phase), n, SOOLI_DEFAULTS) == want, (phase, n)
    v2 = ModeTracker()
    assert v2.observe_call(O("TRICK_PLAY", "project_target_v2"), 3, SOOLI_DEFAULTS) == "O"  # v2 ordinary path only


def test_K05_cold_and_play_modes_are_equivalent_for_bid_search_but_offer_mode_differs(research, mlp, nat, table):
    """The deduced reduction C == P (only play_heur/return_pi reach the rollouts; belief/lambda are
    re-set before every root sooli search) holds on a v3 bid search; O is genuinely different."""
    case, _t = fixture_case("F01", 0)
    obs = tobs_of(case)
    ids = list(case.ordered_action_ids)
    out = {}
    for mode, setting in (("C", (0, False, False, 0.0)), ("P", (17, False, False, 0.3)), ("O", (17, False, True, 0.3))):
        env = nat.Env(128 * 26, 0, table, single_deal=True, encoder=2)
        env.set_sooli(*setting)
        ev, _w = research.trace_search(env, mlp, obs, ids, 32, 6, C.c_uint64(3131))
        out[mode] = ev
    count(probe_ids=["F01-bid-cold", "F01-bid-P-mode-W32", "F01-bid-offer-mode"])
    assert out["C"].work["sooli_resolutions"] > 0, "no rollout reached a sooli: the comparison would be vacuous"
    assert np.array_equal(out["C"].per_world, out["P"].per_world)
    assert not np.array_equal(out["C"].per_world, out["O"].per_world)
    assert len(K.augmented_states()) == 8100
    assert len({(sc, d, tuple(K.reduce_mode(m) for m in modes)) for sc, d, modes in K.augmented_states()}) == 1600


@pytest.fixture(scope="module")
def match():
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity

    eq = Equity.load(EQUITY)
    return eq, K.match_kernel(eq.model)


def test_K06_match_kernel_reproduces_the_equity_table_and_solvers_agree(match):
    eq, kern = match
    assert kern.validate() == [] and len(kern.states) == 100
    direct = kern.solve_direct()
    bounds = kern.solve_bounds(tol=1e-12)
    for (sc, d), v in direct["v"].items():
        assert v == pytest.approx(eq.team0(*sc, d), abs=1e-10), (sc, d)
        assert bounds["lower"][(sc, d)] - 1e-12 <= v <= bounds["upper"][(sc, d)] + 1e-12
    assert direct["residual"] < 1e-12
    # resets and absorption are in the chain: a non-up win from 48-0 returns to 0-0
    row = dict(kern.rows[((48, 0), 1)])
    assert any(y[0] == (0, 0) for y in row) and kern.r0[((48, 0), 1)] > 0


def _toy():
    """v_a = 1/4 + v_a/4 + v_b/2, v_b = 3/10 + v_a/5  ->  v_a = 8/13 (rational inputs, so exact)."""
    F = Fraction
    s = ["a", "b"]
    return K.Kernel(s, {"a": [("b", F(1, 2)), ("a", F(1, 4))], "b": [("a", F(1, 5))]}, {"a": F(1, 4), "b": F(3, 10)},
                    {"b": F(1, 2)})


def test_K06_tiny_kernel_exact_direct_simulation_and_paired_difference():
    k = _toy()
    exact = k.solve_exact()["v"]
    direct = k.solve_direct()["v"]
    assert exact["a"] == Fraction(8, 13) and exact["b"] == Fraction(3, 10) + Fraction(8, 65)
    assert float(exact["a"]) == pytest.approx(direct["a"], abs=1e-14)
    sim = k.simulate("a", 20000, np.random.default_rng(0))
    assert abs(sim["estimate"] - direct["a"]) < 4 * sim["se"] and sim["unfinished"] == 0
    kc = K.Kernel(k.states, {"a": [("b", 0.4), ("a", 0.25)], "b": [("a", 0.2)]}, {"a": 0.35, "b": 0.3}, {"b": 0.5})
    diff = K.paired_difference(k, kc)
    assert diff["a"] == pytest.approx(kc.solve_direct()["v"]["a"] - direct["a"], abs=1e-13)


def test_K07_unobserved_invalid_and_nonabsorbing_rows_are_unresolved():
    s = ["a", "b", "c"]
    est = K.estimate_kernel([{"state": "a", "next": "b", "absorbed": None}, {"state": "b", "next": None, "absorbed": 0}],
                            s)
    with pytest.raises(K.Unresolved, match="unobserved row c"):
        est.solve_direct()
    closed = K.Kernel(["x", "y"], {"x": [("y", 1.0)], "y": [("x", 1.0)]}, {"x": 0.0, "y": 0.0})
    with pytest.raises(K.Unresolved, match="do not contract"):
        closed.solve_bounds()
    with pytest.raises(K.Unresolved):
        closed.solve_exact()
    over = K.Kernel(["x"], {"x": [("x", 0.9)]}, {"x": 0.2})
    with pytest.raises(K.Unresolved, match="sums to"):
        over.solve_direct()


def test_K08_bundle_bootstrap_keeps_whole_bundles_and_separates_numerical_error(monkeypatch):
    rng = np.random.default_rng(5)
    states = ["a", "b"]
    rows = []
    for bundle in range(30):
        for _arm in range(4):  # four correlated rows per deck bundle
            s = "a" if rng.random() < 0.5 else "b"
            u = rng.random()
            rows.append({"bundle": bundle, "state": s, "next": ("b" if s == "a" else "a") if u < 0.5 else None,
                         "absorbed": None if u < 0.5 else (0 if u < 0.8 else 1)})
    sizes = {b: sum(1 for r in rows if r["bundle"] == b) for b in range(30)}
    real = K.estimate_kernel

    def checking(sample, st):
        per = {}
        for r in sample:
            per[r["bundle"]] = per.get(r["bundle"], 0) + 1
        for b, c in per.items():
            assert c % sizes[b] == 0, "a bundle was split"
        return real(sample, st)

    monkeypatch.setattr(K, "estimate_kernel", checking)
    out = K.bundle_bootstrap(rows, states, "a", 40, rng)
    assert out["ci95"][0] <= out["point"] <= out["ci95"][1]
    assert out["max_numerical_residual"] is not None and out["max_numerical_residual"] < 1e-10
    assert "separately" in out["note"]


def test_K09_model_is_named_apart_from_B0_and_wide_overlap_is_not_agreement():
    assert K.MODEL_ID == "C3-marginal-RNG-mode-model-v1" and K.MODEL_ID != K.LITERAL_B0_ID
    assert K.direct_match_agreement(0.60, (0.40, 0.80), (0.35, 0.85), tolerance=0.01) == "unresolved"
    assert K.direct_match_agreement(0.600, (0.598, 0.602), (0.596, 0.604), tolerance=0.005) == "agree"
    assert K.direct_match_agreement(0.60, (0.59, 0.61), (0.70, 0.72), tolerance=0.01) == "disagree"
