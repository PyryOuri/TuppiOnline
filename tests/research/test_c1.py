"""C1 contract tests V01-V10 (V11 is in test_c0_statistics.py).

Exact-law tests use a finite law built from real Tuppi objects: a handful of
root worlds drawn by the native sampler for fixture F02, their exact
continuation values from the explicit-world evaluator and their proxy values.
Expectations and variances are then computed by complete enumeration with
Fractions, independent of the estimator's own arithmetic.
"""

from __future__ import annotations

import ctypes as C
import json
import subprocess
from fractions import Fraction
from itertools import product
from pathlib import Path

import numpy as np
import pytest

from tuppi_ai.research import c1_control_variate as cv
from tuppi_ai.research.ledger import count
from tuppi_ai.research.testing import fixture_case, tobs_of

AI = Path(__file__).resolve().parents[2]


def layouts(worlds):
    return [[w.hand[s] for s in range(4)] for w in worlds]


def brute_liability(root_mask: int, others) -> int:
    """Independent within-suit ducking simulation over explicit cards (V01)."""
    wins = 0
    for suit in range(4):
        piles = [[c for c in range(13 * suit, 13 * suit + 13) if m >> c & 1] for m in [root_mask, *others]]
        while piles[0]:
            played = {i: p.pop(0) for i, p in enumerate(piles) if p}
            if len(played) >= 2 and max(played, key=played.get) == 0:
                wins += 1
    return wins


def test_V01_proxy_equals_independent_enumeration_on_real_and_synthetic_layouts(research, search_env, f02, f02b):
    rng = np.random.default_rng(20260925)
    for case in (f02[0], f02b[0]):
        obs = tobs_of(case)
        for w in research.sample_worlds(search_env, obs, 32, C.c_uint64(99)):
            others = [w.hand[s] for s in range(4) if s != obs.seat]
            for a in case.ordered_action_ids:
                assert cv.contested_liability(w.hand[obs.seat] & ~(1 << a), others) == \
                    brute_liability(w.hand[obs.seat] & ~(1 << a), others)
    for _ in range(300):  # unequal capacities, empty and full suits
        cards = rng.permutation(52)
        sizes = rng.integers(0, 14, 4)
        masks, at = [], 0
        for s in sizes:
            masks.append(int(sum(1 << int(c) for c in cards[at:at + s])))
            at += s
        assert cv.contested_liability(masks[0], masks[1:]) == brute_liability(masks[0], masks[1:])


def test_V01_isolated_research_oracle_agrees():
    out = subprocess.run([str(Path.home() / ".venvs/tuppi-ai/bin/python"), str(AI / "tests/research/oracle_research_suits.py")],
                         check=True, capture_output=True, text=True)
    res = json.loads(out.stdout)
    assert res["engine_modules_loaded"] == [], "RESEARCH oracle loaded the ENGINE installation"
    assert res["layouts_checked"] == 400 and res["layout_mismatches"] == []
    assert len(res["law_rows"]) == 9 and all(r["equal"] for r in res["law_rows"])


def test_V01_removed_card_semantics_and_partner_counts_as_other():
    """A discard is removed, not reassigned; the partner's cards contest like an opponent's."""
    rng = np.random.default_rng(11)
    differs = 0
    for _ in range(400):
        cards = rng.permutation(52)
        masks, at = [], 0
        for s in rng.integers(1, 14, 4):
            masks.append(int(sum(1 << int(c) for c in cards[at:at + s])))
            at += s
        root, others = masks[0], masks[1:]
        held = [c for c in range(52) if root >> c & 1]
        lia = cv.liabilities([root, *others], 0, held)
        for j, a in enumerate(held):
            assert lia[j] == brute_liability(root & ~(1 << a), others)
            given = [others[0] | (1 << a), others[1], others[2]]
            differs += cv.contested_liability(root & ~(1 << a), given) != lia[j]
    assert differs > 0, "reassigning the discard never mattered; the semantics test would be vacuous"
    H = 0
    assert cv.contested_liability(1 << (H + 8), [0, 1 << (H + 0), 0]) == 1   # T vs the partner's 2: contested win
    assert cv.contested_liability(1 << (H + 8), [0, 0, 0]) == 0              # nobody holds hearts: uncontested
    assert cv.contested_liability(1 << (H + 8), [0, 1 << (H + 11), 0]) == 0  # the partner's K beats it


def _dd_value(nat, table, world, action, seat):
    """Independent value of one solver-only rollout: DD tricks -> score -> float32 equity delta, signed."""
    d = nat.TcDeal()
    C.pointer(d)[0] = world
    assert nat.lib.tc_apply(C.byref(d), action) == 0
    nat.lib.tc_finish_with_tricks.argtypes = [C.POINTER(nat.TcDeal), C.c_int]
    nat.lib.tc_finish_with_tricks(C.byref(d), nat.dd_team0_tricks(d))
    after = (C.c_uint8 * 2)()
    nat.lib.tc_next_score(d.score, d.winner_team, d.points, after)

    def eq(s0, s1, dealer):
        if s0 >= 52:
            return 1.0
        if s1 >= 52:
            return 0.0
        row = 0 if s0 == 0 and s1 == 0 else (s0 // 4 if s0 else 12 + s1 // 4)
        return table[row][1 if dealer % 2 == 0 else 0]

    delta = np.float32(eq(after[0], after[1], d.dealer + 1) - eq(d.score[0], d.score[1], d.dealer))
    return float(delta) * (1.0 if seat % 2 == 0 else -1.0)


@pytest.mark.parametrize("fid,index", [("F02", 0), ("F02", 2)])
def test_V01_target_sign_for_both_teams_on_solver_only_discards(research, nat, mlp, table, search_env, fid, index):
    case, _truth = fixture_case(fid, index)
    obs = tobs_of(case)
    assert 13 - (obs.n_played >> 2) <= 6, "needs a solver-only position"
    ids = list(case.ordered_action_ids)
    worlds = research.sample_worlds(search_env, obs, 8, C.c_uint64(5))
    ev = research.evaluate_worlds(search_env, mlp, obs, worlds, ids, 6)
    for wi, w in enumerate(worlds):
        for ai, a in enumerate(ids):
            assert ev.per_world[wi, ai] == _dd_value(nat, table, w, a, obs.seat)
    assert {obs.seat % 2 for obs in [tobs_of(fixture_case("F02", 0)[0]), tobs_of(fixture_case("F02", 2)[0])]} == {0, 1}


def test_V02_proxy_varies_on_F02_and_a_constant_proxy_gives_no_gain(research, search_env, f02):
    obs = tobs_of(f02[0])
    ids = list(f02[0].ordered_action_ids)
    g = cv.proxy_matrix(layouts(research.sample_worlds(search_env, obs, 64, C.c_uint64(3))), obs.seat, ids, 0)
    assert any(len(set(g[:, j])) > 1 for j in range(len(ids))), "vacuous proxy on F02"
    # F02t0 is a real case where the proxy is constant across worlds: identical to plain MC for every beta
    case0, _t = fixture_case("F02", 2)
    o0 = tobs_of(case0)
    g0 = cv.proxy_matrix(layouts(research.sample_worlds(search_env, o0, 64, C.c_uint64(4))), o0.seat,
                         list(case0.ordered_action_ids), 0)
    assert all(len(set(g0[:, j])) == 1 for j in range(g0.shape[1]))
    d = np.random.default_rng(1).normal(size=(10, g0.shape[1]))
    d[:, 0] = 0
    for beta in (0.0, 0.5, -2.0):
        est = cv.estimate_gaps(g0[:7], d, g0[:10], beta, 0)
        assert np.allclose(est.gaps, cv.plain_gaps(d)) and np.allclose(est.variance, d.var(0, ddof=1) / 10)


@pytest.fixture(scope="module")
def finite_law(research, mlp, table):
    """A finite law of six distinct F02 worlds with exact values D and proxy G."""
    import tuppi_ai.native as nat

    case, _t = fixture_case("F02", 0)
    obs = tobs_of(case)
    ids = list(case.ordered_action_ids)
    env = nat.Env(128 * 26, 0, table, single_deal=True, encoder=2)
    worlds, seen = [], set()
    for w in research.sample_worlds(env, obs, 64, C.c_uint64(17)):
        key = tuple(w.hand[s] for s in range(4))
        if key not in seen:
            seen.add(key)
            worlds.append(w)
        if len(worlds) == 6:
            break
    ev = research.evaluate_worlds(env, mlp, obs, worlds, ids, 6)
    ref = 0
    d = ev.per_world - ev.per_world[:, [ref]]
    g = cv.proxy_matrix(layouts(worlds), obs.seat, ids, ref)
    return {"D": d, "G": g, "ref": ref, "ids": ids}


def _exact(values):
    return [Fraction(float(v)) for v in values]


def _law_moments(xs):
    n = len(xs)
    m = sum(xs, Fraction(0)) / n
    return m, sum(((x - m) ** 2 for x in xs), Fraction(0)) / n


def _estimator_law(d_col, g_col, beta, M, n, dependent=False):
    """Exact distribution of the estimator under i.i.d. uniform draws (with replacement)."""
    W = len(d_col)
    b = Fraction(beta)
    outs = []
    if dependent:  # cheap batch = the expensive batch's own worlds (M == n)
        for idx in product(range(W), repeat=n):
            mu = sum((g_col[i] for i in idx), Fraction(0)) / n
            res = sum((d_col[i] - b * g_col[i] for i in idx), Fraction(0)) / n
            outs.append(b * mu + res)
    else:
        for cheap in product(range(W), repeat=M):
            mu = sum((g_col[i] for i in cheap), Fraction(0)) / M
            for exp in product(range(W), repeat=n):
                res = sum((d_col[i] - b * g_col[i] for i in exp), Fraction(0)) / n
                outs.append(b * mu + res)
    return _law_moments(outs)


def test_V03_correction_is_unbiased_for_correct_wrong_reversed_and_constant_proxies(finite_law):
    d, g = finite_law["D"], finite_law["G"]
    rng = np.random.default_rng(7)
    wrong = rng.integers(-3, 4, size=g.shape).astype(float)
    wrong[:, finite_law["ref"]] = 0
    proxies = {"correct": g, "wrong": wrong, "reversed": -g, "constant": np.ones_like(g) * (g.mean(0))}
    j = next(k for k in range(g.shape[1]) if len(set(g[:, k])) > 1 and k != finite_law["ref"])
    target, _ = _law_moments(_exact(d[:, j]))
    for name, gp in proxies.items():
        for beta in (0.0, 0.37, -1.5):
            for M, n in ((1, 1), (2, 2)):
                mean, _var = _estimator_law(_exact(d[:, j]), _exact(gp[:, j]), beta, M, n)
                assert mean == target, (name, beta, M, n)


def test_V04_independent_batch_variance_formula_holds_and_dependent_batches_break_it(finite_law):
    d, g = finite_law["D"], finite_law["G"]
    j = next(k for k in range(g.shape[1]) if len(set(g[:, k])) > 1 and k != finite_law["ref"])
    dj, gj = _exact(d[:, j]), _exact(g[:, j])
    broke = False
    for beta in (0.37, 1.0, -0.8):
        b = Fraction(beta)
        _m, var_g = _law_moments(gj)
        _m, var_r = _law_moments([x - b * y for x, y in zip(dj, gj)])
        for M, n in ((1, 1), (2, 2), (1, 2)):
            _mean, var = _estimator_law(dj, gj, beta, M, n)
            assert var == b * b * var_g / M + var_r / n
        _mean, dep = _estimator_law(dj, gj, beta, 2, 2, dependent=True)
        broke |= dep != b * b * var_g / 2 + var_r / 2
    assert broke, "the dependent-batch control never violated the independent-batch formula"


def test_V05_degenerate_cases():
    rng = np.random.default_rng(2)
    d = rng.normal(size=(9, 4))
    d[:, 0] = 0
    g = rng.normal(size=(9, 4))
    g[:, 0] = 0
    est = cv.estimate_gaps(g[:5], d, g, 0.0, 0)
    assert np.array_equal(est.gaps, cv.plain_gaps(d)) and est.gaps[0] == 0.0
    assert cv.fit_beta([(d, np.zeros_like(d), 0)])["beta"] == 0.0            # zero proxy variance
    flat = cv.estimate_gaps(np.zeros((3, 4)), np.zeros((4, 4)), np.zeros((4, 4)), 0.7, 0)
    assert np.all(flat.gaps == 0) and cv.select(flat.gaps) == 0              # all-equal -> reference, first
    with pytest.raises(ValueError):
        cv.estimate_gaps(np.zeros((0, 4)), d, g, 0.5, 0)                     # beta != 0 needs a cheap batch
    bad = d.copy()
    bad[0, 0] = 1.0
    with pytest.raises(ValueError):
        cv.estimate_gaps(g[:5], bad, g, 0.5, 0)                              # reference gap must be exactly 0
    with pytest.raises(ValueError):
        cv.estimate_gaps(g[:5], d * np.nan, g, 0.5, 0)
    alloc = cv.allocate(np.zeros(3), np.ones(3), 1.0, 10.0, 100.0)
    assert alloc["M"] == 0 and alloc["n"] == 10                              # A = 0: nothing on the cheap batch
    alloc = cv.allocate(np.ones(3), np.zeros(3), 1.0, 10.0, 100.0)
    assert alloc["n"] == 2                                                   # B = 0: minimum expensive batch


def test_V05_beta_fit_centres_within_case_and_action():
    """A between-case strength difference shared by D and G must not manufacture correlation."""
    rng = np.random.default_rng(3)
    cases = []
    for c in range(6):
        g = rng.normal(size=(40, 3))
        g[:, 0] = 0
        d = 0.25 * g + 0.05 * rng.normal(size=(40, 3))
        d[:, 0] = 0
        shift = 10.0 * c * np.array([0.0, 1.0, -3.0])  # huge per-case AND per-action offsets in D and G
        g += shift
        d += shift * 2.0
        cases.append((d, g, 0))
    beta = cv.fit_beta(cases)["beta"]
    assert abs(beta - 0.25) < 0.03


def test_V06_explicit_world_values_reproduce_the_traced_search_and_never_resample(research, mlp, search_env, f02b):
    obs = tobs_of(f02b[0])
    ids = list(f02b[0].ordered_action_ids)
    rng = C.c_uint64(424242)
    traced, worlds = research.trace_search(search_env, mlp, obs, ids, 128, 6, rng)
    count(probe_ids=["F02b-discard-pos3"])
    before = [bytes(w) for w in worlds]
    cont = C.c_uint64(77)
    ev = research.evaluate_worlds(search_env, mlp, obs, worlds, ids, 6, cont)
    assert np.array_equal(ev.per_world, traced.per_world) and np.array_equal(ev.values, traced.values)
    assert cont.value == 77 and [bytes(w) for w in worlds] == before
    assert traced.work["mlp_rows"] > 0 and ev.valid.all()
    dup = research.evaluate_worlds(search_env, mlp, obs, [worlds[3]] * 4, ids, 6)
    assert all(np.array_equal(dup.per_world[i], traced.per_world[3]) for i in range(4))


def test_V07_action_reorder_permutes_only_the_matching_columns(research, mlp, search_env, f02b):
    obs = tobs_of(f02b[0])
    ids = list(f02b[0].ordered_action_ids)
    worlds = research.sample_worlds(search_env, obs, 32, C.c_uint64(8080))
    before = [bytes(w) for w in worlds]
    base = research.evaluate_worlds(search_env, mlp, obs, worlds, ids, 6)
    perm = list(reversed(range(len(ids))))
    moved = research.evaluate_worlds(search_env, mlp, obs, worlds, [ids[i] for i in perm], 6)
    assert base.work["mlp_rows"] > 0
    assert np.array_equal(moved.per_world, base.per_world[:, perm])
    sub = research.evaluate_worlds(search_env, mlp, obs, worlds, ids[:2], 6)
    assert np.array_equal(sub.per_world, base.per_world[:, :2])
    assert [bytes(w) for w in worlds] == before


def test_V08_split_overlap_is_rejected_and_streams_are_independent():
    from tuppi_ai.research.records import SplitLeakError, SplitRegistry, parent_deal_id
    from tuppi_ai.research.streams import stream_seed

    reg = SplitRegistry()
    for i in range(4):
        reg.assign(parent_deal_id("c1-fit", i), "FIT")
        reg.assign(parent_deal_id("c1-plan", i), "PLAN")
    with pytest.raises(SplitLeakError):
        reg.assign(parent_deal_id("c1-fit", 2), "PLAN")
    with pytest.raises(SplitLeakError):
        reg.check_record(parent_deal_id("c1-plan", 1), "SCREEN")
    with pytest.raises(SplitLeakError):
        SplitRegistry.check_disjoint({"PLAN": ["a", "b"], "SCREEN": ["c", "a"]})
    seeds = {ns: stream_seed(ns, "run", 3, 5) for ns in ("fit", "plan", "screen", "confirm", "cheap", "expensive",
                                                         "reference", "validation")}
    assert len(set(seeds.values())) == len(seeds)
    with pytest.raises(ValueError):
        stream_seed("cheap", "world", 3)


def _fresh_best(seat, seed=21):
    from tuppi_ai.research.lifecycle import AgentSpec

    return AgentSpec.of("best", seat, worlds=128, seed=seed).construct()


def test_V09_shadow_advancement_matches_W128_state_and_natural_streams_differ(research):
    from tuppi_ai.research.c1_dispatch import C1Candidate, C1Config
    from tuppi_ai.research.lifecycle import snapshot

    seq = [fixture_case("F02", 1)[0].policy_observation(), fixture_case("F02", 0)[0].policy_observation()]
    seat = seq[0].observing_seat
    original = _fresh_best(seat)
    shadow = C1Candidate(_fresh_best(seat), C1Config(beta=0.5, m_cheap=64, n_expensive=16, run_id="contract-V09"), research)
    natural = C1Candidate(_fresh_best(seat), C1Config(beta=0.5, m_cheap=64, n_expensive=16,
                                                      run_id="contract-V09", advancement="natural"), research)
    count(probe_ids=["F02b-discard-pos3", "F02-discard-pos2"])
    for obs in seq:
        original.choose_action(obs)
        a_shadow = shadow.choose_action(obs)
        natural.choose_action(obs)
        assert a_shadow in obs.legal_actions
        assert snapshot(shadow.base, research) == snapshot(original, research)
        assert snapshot(natural.base, research) != snapshot(original, research)
    assert len(shadow.decisions) == 2 and "shadow" in shadow.decisions[0].candidate_id
    assert "natural" in natural.decisions[0].candidate_id
    assert shadow.decisions[0].candidate_id != natural.decisions[0].candidate_id


def test_V09_non_eligible_calls_delegate_unchanged(research):
    from tuppi_ai.research.c1_dispatch import C1Candidate, C1Config, eligible
    from tuppi_ai.research.lifecycle import snapshot

    obs = fixture_case("F05", 0)[0].policy_observation()      # a lead, not a discard
    assert not eligible(obs)
    base, wrapped = _fresh_best(obs.observing_seat), C1Candidate(_fresh_best(obs.observing_seat),
                                                                 C1Config(0.5, 8, 4, "contract-V09"), research)
    count(probe_ids=["F05-three-card-lead"])
    assert base.choose_action(obs) == wrapped.choose_action(obs)
    assert base.last_values == wrapped.base.last_values and not wrapped.decisions
    assert snapshot(base, research) == snapshot(wrapped.base, research)


def test_V10_cost_accounts_every_component_and_total_saving_is_bounded(research):
    from tuppi_ai.research.c1_dispatch import C1Candidate, C1Config
    from tuppi_ai.research.statistics import total_saving_bound

    obs = fixture_case("F02", 0)[0].policy_observation()
    cand = C1Candidate(_fresh_best(obs.observing_seat), C1Config(0.5, 64, 16, "contract-V10"), research)
    cand.choose_action(obs)
    cost = cand.decisions[0].cost
    parts = ("reference_cpu_s", "sampling_cpu_s", "expensive_cpu_s", "proxy_cpu_s", "shadow_cpu_s")
    assert all(cost[p] >= 0 for p in parts) and sum(cost[p] for p in parts) <= cost["total_cpu_s"] + 1e-6
    assert cost["work"]["first_actions"] == 16 * len(cand.decisions[0].ids)
    b = total_saving_bound(0.1, 0.5, overhead_fraction=0.01)
    assert b["upper_bound_before_overhead"] == pytest.approx(0.05) and b["net_bound"] == pytest.approx(0.04)
    with pytest.raises(ValueError):
        total_saving_bound(1.5, 0.2)


def implementation_law(estimator, d, g, beta, ref, j, M, n):
    """Exact mean and variance of the implementation's gap, and the mean of its variance field."""
    W = d.shape[0]
    gaps, vars_ = [], []
    for cheap in product(range(W), repeat=M):
        for exp in product(range(W), repeat=n):
            est = estimator(g[list(cheap)], d[list(exp)], g[list(exp)], beta, ref)
            gaps.append(Fraction(float(est.gaps[j])))
            vars_.append(Fraction(float(est.variance[j])))
    mean, var = _law_moments(gaps)
    return mean, var, sum(vars_, Fraction(0)) / len(vars_)


def _unbiased(estimator, finite_law, beta, M, n, tol=1e-12, column=None):
    d, g, ref = finite_law["D"], finite_law["G"], finite_law["ref"]
    j = column if column is not None else next(k for k in range(g.shape[1]) if len(set(g[:, k])) > 1 and k != ref)
    target, var_d = _law_moments(_exact(d[:, j]))
    mean, actual_var, mean_var = implementation_law(estimator, d, g, beta, ref, j, M, n)
    _m, var_g = _law_moments(_exact(g[:, j]))
    _m, var_r = _law_moments([x - Fraction(beta) * y for x, y in zip(_exact(d[:, j]), _exact(g[:, j]))])
    true_var = Fraction(beta) ** 2 * var_g / M + var_r / n
    # sample variances (ddof=1) are unbiased for the population variances of i.i.d. draws
    ok_mean = abs(float(mean - target)) <= tol * max(1.0, abs(float(target)))
    ok_field = abs(float(mean_var - true_var)) <= tol * max(1.0, abs(float(true_var)))
    ok_actual = abs(float(actual_var - true_var)) <= tol * max(1.0, abs(float(true_var)))
    return ok_mean, ok_field, ok_actual


def test_V03_V04_the_implementation_is_unbiased_with_an_unbiased_variance_field(finite_law):
    for beta in (0.0, 0.37, -1.5):
        assert _unbiased(cv.estimate_gaps, finite_law, beta, 2, 2) == (True, True, True), beta
    assert _unbiased(cv.estimate_gaps, finite_law, 0.37, 3, 2) == (True, True, True)


def test_V03_V04_the_check_detects_a_biased_or_dependent_estimator(finite_law):
    """Mutation control: the enumeration check must reject wrong estimators."""
    def cheap_only(gc, d, ge, beta, ref):   # forgets the -beta*G correction on the expensive batch
        est = cv.estimate_gaps(gc, d, ge, beta, ref)
        return cv.GapEstimate(est.gaps + beta * est.mu_g * 0 + beta * ge.mean(0), est.mu_g, est.residual,
                              est.variance, beta, est.m, est.n, ref)

    def reuses_expensive(gc, d, ge, beta, ref):  # "cheap" batch silently replaced by the expensive worlds
        return cv.estimate_gaps(ge, d, ge, beta, ref)

    assert _unbiased(cheap_only, finite_law, 0.37, 2, 2)[0] is False
    mean_ok, field_ok, actual_ok = _unbiased(reuses_expensive, finite_law, 0.37, 2, 2)
    assert mean_ok and field_ok and actual_ok is False  # unbiased, but its uncertainty formula is wrong


def test_V03_the_implementation_is_unbiased_for_wrong_reversed_and_constant_proxies(finite_law):
    """Every proxy runs through cv.estimate_gaps itself, not only through the enumeration formula."""
    d, g, ref = finite_law["D"], finite_law["G"], finite_law["ref"]
    rng = np.random.default_rng(7)
    wrong = rng.integers(-3, 4, size=g.shape).astype(float)
    wrong[:, ref] = 0
    const = np.ones_like(g) * g.mean(0)
    j = next(k for k in range(g.shape[1]) if len(set(g[:, k])) > 1 and k != ref)  # a column D varies in
    for name, gp in {"wrong": wrong, "reversed": -g, "constant": const}.items():
        mean_ok, field_ok, actual_ok = _unbiased(cv.estimate_gaps, dict(finite_law, G=gp), 0.37, 2, 2, column=j)
        assert mean_ok and field_ok and actual_ok, name


def test_V05_one_cheap_draw_with_nonzero_beta_has_no_variance_estimate():
    rng = np.random.default_rng(4)
    d = rng.normal(size=(5, 3))
    d[:, 0] = 0
    g = rng.normal(size=(5, 3))
    g[:, 0] = 0
    assert np.isnan(cv.estimate_gaps(g[:1], d, g, 0.4, 0).variance[1:]).all()
    assert np.isfinite(cv.estimate_gaps(g[:1], d, g, 0.0, 0).variance).all()
    from tuppi_ai.research.c1_dispatch import C1Config
    with pytest.raises(ValueError):
        C1Config(0.4, 1, 8, "x")
    with pytest.raises(ValueError):
        C1Config(0.4, 8, 8, "")
    assert cv.optimal_beta(0.5, 256, 32) == pytest.approx(0.5 * 256 / 288)


def test_V08_beta_fitting_accepts_only_FIT_parents():
    from tuppi_ai.research.records import SplitLeakError, SplitRegistry, parent_deal_id

    reg = SplitRegistry()
    fit, plan = parent_deal_id("c1-fit-v1", 0), parent_deal_id("c1-plan-v1", 0)
    reg.assign(fit, "FIT")
    reg.assign(plan, "PLAN")
    rng = np.random.default_rng(1)
    d, g = rng.normal(size=(6, 3)), rng.normal(size=(6, 3))
    assert cv.fit_beta_on_split([(fit, d, g, 0)], reg)["split"] == "FIT"
    with pytest.raises(SplitLeakError):
        cv.fit_beta_on_split([(fit, d, g, 0), (plan, d, g, 0)], reg)


def test_V09_experiment_streams_follow_the_agents_own_state_not_the_case(research):
    """Distinct agents (seeds) get distinct streams on the same observation; a fork reproduces them."""
    from tuppi_ai.research.c1_dispatch import C1Candidate, C1Config
    from tuppi_ai.research.lifecycle import AgentSpec, RecordingAgent, replay_fork, snapshot

    obs = fixture_case("F02", 0)[0].policy_observation()
    seat = obs.observing_seat
    cfg = C1Config(0.5, 32, 8, "contract-streams")
    a = C1Candidate(_fresh_best(seat, seed=1), cfg, research)
    b = C1Candidate(_fresh_best(seat, seed=2), cfg, research)
    a.choose_action(obs)
    b.choose_action(obs)
    assert a.decisions[0].gaps != b.decisions[0].gaps  # independent experiment streams per agent
    spec = AgentSpec.of("c1", seat, beta=0.5, m_cheap=32, n_expensive=8, run_id="contract-streams", seed=1)
    live = RecordingAgent(spec)
    live.choose_action(obs)
    assert live.agent.decisions[0].gaps == a.decisions[0].gaps  # the factory builds the same candidate
    fork = replay_fork(spec, live.history)
    assert snapshot(fork.agent, research) == snapshot(live.agent, research)
    assert snapshot(live.agent, research)["type"] == "C1Candidate" and snapshot(live.agent, research)["base"]["searcher"]


def test_V09_a_failed_C1_branch_falls_back_to_W128_and_is_recorded(research, monkeypatch):
    from tuppi_ai.research.c1_dispatch import C1Candidate, C1Config
    from tuppi_ai.research.lifecycle import snapshot

    obs = fixture_case("F02", 0)[0].policy_observation()
    original = _fresh_best(obs.observing_seat)
    cand = C1Candidate(_fresh_best(obs.observing_seat), C1Config(0.5, 16, 8, "contract-fallback"), research)

    def boom(*a, **k):
        raise RuntimeError("deliberate evaluator failure")

    monkeypatch.setattr(research, "evaluate_worlds", boom)
    got = cand.choose_action(obs)
    monkeypatch.undo()
    assert got == original.choose_action(obs)
    assert cand.fallbacks == 1 and "deliberate" in cand.failures[0]["error"]
    assert not cand.failures[0]["rng_advanced_before_fallback"]
    assert snapshot(cand.base, research) == snapshot(original, research)


def test_A08_the_C1_candidate_sees_only_its_observation(research):
    """F02's actor decides identically when two other seats' hidden cards are swapped consistently."""
    from tuppi_engine import match_observation_for, observation_to_data

    from tuppi_ai.research.c1_dispatch import C1Candidate, C1Config
    from tuppi_ai.research.fixtures import _card_from_code, make_truth, replay
    from tuppi_ai.research.records import OfflineTruth

    case, truth = fixture_case("F02", 0)
    obs = case.policy_observation()
    root = obs.observing_seat
    seen = {c for t in obs.completed_tricks for c in (p.card for p in t.plays)} | {p.card for p in obs.current_trick}
    hands = [list(h) for h in truth.initial_hands]
    others = [s for s in range(4) if s != root]
    swapped = None
    for a_seat in others:
        for b_seat in others:
            if a_seat >= b_seat:
                continue
            for ca in hands[a_seat]:
                for cb in hands[b_seat]:
                    x, y = _card_from_code(ca), _card_from_code(cb)
                    if x.suit != y.suit or x in seen or y in seen:
                        continue
                    trial = [list(h) for h in hands]
                    trial[a_seat][trial[a_seat].index(ca)] = cb
                    trial[b_seat][trial[b_seat].index(cb)] = ca
                    alt = OfflineTruth(truth.cluster_id, truth.ruleset, truth.dealer, truth.starting_score,
                                       tuple(tuple(h) for h in trial), truth.action_history)
                    try:
                        state = replay(alt, case_history_len(truth, obs))
                    except Exception:
                        continue
                    alt_obs = match_observation_for(state, root)
                    if observation_to_data(alt_obs) == case.observation:
                        swapped = alt_obs
                        break
                if swapped:
                    break
            if swapped:
                break
        if swapped:
            break
    assert swapped is not None, "no consistent hidden swap found"
    decide = lambda o: C1Candidate(_fresh_best(root, seed=9), C1Config(0.5, 32, 8, "contract-A08"), research)  # noqa: E731
    one, two = decide(obs), decide(swapped)
    assert one.choose_action(obs) == two.choose_action(swapped)
    assert one.decisions[0].gaps == two.decisions[0].gaps


def case_history_len(truth, obs) -> int:
    """How many recorded actions precede this observation (shows + plays)."""
    return len(obs.show_actions) + sum(len(t.plays) for t in obs.completed_tricks) + len(obs.current_trick)
