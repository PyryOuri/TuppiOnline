"""C4.02 contract tests X04, X05, X06, X08, X11, X12 on exact finite fixtures (no real-bank training)."""

from __future__ import annotations

from itertools import product

import numpy as np
import pytest

from tuppi_ai.research import c4_training as T


def two_world_problem():
    """The receiver cannot tell W1 from W2; the giver can. Payoffs make the convention matter."""
    worlds = ["W1", "W2"]
    pay = {("W1", "a", "r1"): 1, ("W1", "a", "r2"): 0, ("W1", "b", "r1"): 0, ("W1", "b", "r2"): 3,
           ("W2", "a", "r1"): 0, ("W2", "a", "r2"): 2, ("W2", "b", "r1"): 1, ("W2", "b", "r2"): 0}
    return T.ExchangeProblem(worlds, {"W1": 0.5, "W2": 0.5}, {"W1": "h1", "W2": "h2"}, {"W1": "P", "W2": "P"},
                             {w: ["a", "b"] for w in worlds},
                             {(w, g): ["r1", "r2"] for w in worlds for g in ("a", "b")}, pay)


CONVENTION = {"h1": {"a": 1.0}, "h2": {"b": 1.0}}


def test_X04_receiver_targets_weighted_by_the_giver_learn_the_convention_uniform_ones_do_not():
    prob = two_world_problem()
    weighted = T.receiver_best_response(prob, CONVENTION, weighted=True)
    uniform = T.receiver_best_response(prob, CONVENTION, weighted=False)
    assert weighted[("P", "a")] == {"r1": 1.0} and weighted[("P", "b")] == {"r1": 1.0}
    assert uniform[("P", "a")] == {"r2": 1.0} and uniform[("P", "b")] == {"r2": 1.0}
    assert prob.value(CONVENTION, weighted) == 1.0 and prob.value(CONVENTION, uniform) == 0.0


def test_X05_sampled_messages_need_support_and_E_over_mu_weights():
    prob = two_world_problem()
    E = {"h1": {"a": 0.7, "b": 0.3}, "h2": {"a": 0.2, "b": 0.8}}
    mu = {"h1": {"a": 0.5, "b": 0.5}, "h2": {"a": 0.5, "b": 0.5}}
    exact = T.receiver_values(prob, E, weighted=True)
    # enumerate every single-draw outcome per world (each has probability 1/4 under mu)
    acc: dict = {}
    for g1, g2 in product("ab", "ab"):
        est = T.importance_receiver_values(prob, E, mu, {"W1": [g1], "W2": [g2]})
        for key, vals in est.items():
            for r, v in vals.items():
                acc.setdefault(key, {}).setdefault(r, 0.0)
                acc[key][r] += v * mu["h1"][g1] * mu["h2"][g2]
    for key, vals in exact.items():
        for r, v in vals.items():
            assert acc[key][r] == pytest.approx(v, abs=1e-15)
    with pytest.raises(ValueError, match="no support"):
        T.importance_receiver_values(prob, E, {"h1": {"b": 1.0}, "h2": mu["h2"]}, {"W1": ["b"], "W2": ["a"]})


def test_X06_a_soft_trained_receiver_is_recalibrated_under_the_greedy_giver():
    prob = two_world_problem()
    E_soft = {"h1": {"a": 0.6, "b": 0.4}, "h2": {"a": 0.4, "b": 0.6}}
    R_soft = T.complete_receiver(prob, T.receiver_best_response(prob, E_soft, True))
    out = T.deploy_greedy(prob, E_soft, R_soft)
    assert out["E_greedy"] == CONVENTION
    assert out["J_greedy_with_soft_receiver"] == 0.0 and out["J_greedy_recalibrated"] == 1.0
    # the soft pair looks perfect (1.0) while its greedy conversion with the same receiver scores 0.0:
    # a soft-policy result does not validate the greedy policy
    assert out["J_soft"] == 1.0 and out["J_soft"] != out["J_greedy_with_soft_receiver"]


def harmful_signal_problem():
    """Giving the world's signal card reveals the world but costs survival; a safe give needs no message."""
    worlds = ["W1", "W2"]
    gives = {w: ["sig1", "sig2", "safe"] for w in worlds}
    returns = {(w, g): ["r1", "r2"] for w in worlds for g in gives[w]}
    pay = {}
    for w, good in (("W1", "r1"), ("W2", "r2")):
        for g in gives[w]:
            for r in ("r1", "r2"):
                pay[(w, g, r)] = 0.8 if g == "safe" else (0.5 if r == good else 0.0)
    return T.ExchangeProblem(worlds, {"W1": 0.5, "W2": 0.5}, {"W1": "h1", "W2": "h2"}, {"W1": "P", "W2": "P"},
                             gives, returns, pay)


def test_X08_an_informative_but_harmful_message_loses_and_the_optimiser_drops_it():
    prob = harmful_signal_problem()
    signalling = {"h1": {"sig1": 1.0}, "h2": {"sig2": 1.0}}
    R_sig = T.complete_receiver(prob, T.receiver_best_response(prob, signalling))
    assert prob.value(signalling, R_sig) == pytest.approx(0.5)
    run = T.alternate(prob, signalling, rounds=2)
    assert run["E"] == {"h1": {"safe": 1.0}, "h2": {"safe": 1.0}}
    assert max(run["values"]) == pytest.approx(0.8) and run["values"][0] == pytest.approx(0.5)
    # a message the giver never sends gets the declared out-of-distribution fallback, not a meaning
    assert run["R"][("P", "sig2")] == {"r1": 1.0}
    with pytest.raises(ValueError):
        T.alternate(prob, signalling, rounds=4)


def test_X11_joint_versus_each_single_uses_simultaneous_intervals():
    rng = np.random.default_rng(8)
    n = 400
    j00 = rng.normal(0.50, 0.1, n)
    j10 = j00 + 0.05 + rng.normal(0, 0.02, n)
    j01 = j00 + 0.01 + rng.normal(0, 0.02, n)
    same = T.four_arm_analysis(j00, j10, j01, j10 + rng.normal(0, 0.02, n))  # joint == the giver-only arm
    assert not same["joint_beats_each_single"]
    better = T.four_arm_analysis(j00, j10, j01, j10 + 0.03 + rng.normal(0, 0.02, n))
    assert better["joint_beats_each_single"] and "Bonferroni" in better["multiplicity"]
    s = better["J11_minus_J10_simultaneous"]
    assert s["ci"][1] - s["mean"] == pytest.approx(T.Z_SIMULTANEOUS_2 * s["se"])
    with pytest.raises(ValueError):
        T.four_arm_analysis([1.0], [1.0], [1.0], [1.0])


def test_X12_convention_aware_defence_is_unresolved_without_justified_weights():
    assert T.convention_aware_defender_status()["status"] == "UNRESOLVED"
    with pytest.raises(NotImplementedError):
        T.reweight_native_sooli_draws(None, None)
    assert T.convention_aware_defender_status(validated_generative_sampler="sampler-v1")["status"] == "READY_FOR_REVIEW"
