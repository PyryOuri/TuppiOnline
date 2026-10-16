"""C4.02: the giver-weighted joint exchange objective, on exact finite fixtures (section 7.4-7.5).

A finite exchange problem has worlds w with prior mass pi(w), the giver's
legal information key h(w), the receiver's key p(w) (everything it sees
except the message), legal gives G(w), legal returns R(w, g) and actual
payoffs T_w[g, r]. Decentralised policies E(g | h) and Rv(r | p, g) give

    J(E, Rv) = sum_w pi(w) sum_g E(g | h(w)) sum_r Rv(r | p(w), g) T_w[g, r].

The receiver's value of r after (p, g) WEIGHTS every world by the giver's
probability of sending g there: a receiver trained on uniformly enumerated
messages does not learn the giver's convention (X04). Nothing here trains on
real banks; P.C4 needs an approved manifest.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

Z_SIMULTANEOUS_2 = 2.241402727604947  # two-sided 95% Bonferroni for 2 comparisons (alpha/4 each tail)


@dataclass
class ExchangeProblem:
    worlds: list            # world ids
    prior: dict             # w -> mass
    h: dict                 # w -> giver key
    p: dict                 # w -> receiver key (without the message)
    gives: dict             # w -> legal gives
    returns: dict           # (w, g) -> legal returns
    T: dict                 # (w, g, r) -> payoff

    def value(self, E: dict, Rv: dict) -> float:
        total = 0.0
        for w in self.worlds:
            for g in self.gives[w]:
                eg = E[self.h[w]].get(g, 0.0)
                if eg:
                    total += self.prior[w] * eg * sum(Rv[(self.p[w], g)].get(r, 0.0) * self.T[(w, g, r)]
                                                      for r in self.returns[(w, g)])
        return total


def _argmax(values: dict):
    return max(sorted(values), key=lambda k: values[k])  # ties: smallest key


def point(dist_key):
    return {dist_key: 1.0}


def receiver_values(prob: ExchangeProblem, E: dict, weighted: bool = True) -> dict:
    """(p, g) -> {r: value}. weighted=False is the deliberate error: every world counts, whatever E sends."""
    out: dict = {}
    for w in prob.worlds:
        for g in prob.gives[w]:
            weight = prob.prior[w] * (E[prob.h[w]].get(g, 0.0) if weighted else 1.0)
            vals = out.setdefault((prob.p[w], g), {})
            for r in prob.returns[(w, g)]:
                vals[r] = vals.get(r, 0.0) + weight * prob.T[(w, g, r)]
    return out


def receiver_best_response(prob, E, weighted=True, temperature: float = 0.0) -> dict:
    rv = {}
    for key, vals in receiver_values(prob, E, weighted).items():
        rv[key] = point(_argmax(vals)) if temperature == 0 else _soft(vals, temperature)
    return rv


def giver_values(prob, Rv) -> dict:
    out: dict = {}
    for w in prob.worlds:
        vals = out.setdefault(prob.h[w], {})
        for g in prob.gives[w]:
            v = sum(Rv[(prob.p[w], g)].get(r, 0.0) * prob.T[(w, g, r)] for r in prob.returns[(w, g)])
            vals[g] = vals.get(g, 0.0) + prob.prior[w] * v
    return out


def giver_best_response(prob, Rv, temperature: float = 0.0) -> dict:
    return {h: point(_argmax(vals)) if temperature == 0 else _soft(vals, temperature)
            for h, vals in giver_values(prob, Rv).items()}


def _soft(vals: dict, temperature: float) -> dict:
    keys = sorted(vals)
    z = np.array([vals[k] for k in keys]) / temperature
    z -= z.max()
    p = np.exp(z)
    p /= p.sum()
    return dict(zip(keys, p.tolist()))


def complete_receiver(prob, Rv, default="first") -> dict:
    """A declared out-of-distribution fallback for every (p, g) the giver never sends."""
    out = dict(Rv)
    for w in prob.worlds:
        for g in prob.gives[w]:
            key = (prob.p[w], g)
            if key not in out or not out[key]:
                out[key] = point(sorted(prob.returns[(w, g)])[0])
    return out


def alternate(prob, E0: dict, rounds: int = 3, temperature: float = 0.0) -> dict:
    """At most `rounds` receiver-then-giver improvements (spec cap 3), each receiver weighted by the giver."""
    if rounds > 3:
        raise ValueError("C4v1 caps alternation at 3 rounds")
    E, history = E0, []
    Rv = complete_receiver(prob, receiver_best_response(prob, E, True, temperature))
    for _ in range(rounds):
        Rv = complete_receiver(prob, receiver_best_response(prob, E, True, temperature))
        history.append(prob.value(E, Rv))
        E = giver_best_response(prob, Rv, temperature)
        history.append(prob.value(E, Rv))
    return {"E": E, "R": Rv, "values": history}


def deploy_greedy(prob, E_soft: dict, R_soft: dict) -> dict:
    """Greedy deployment of a soft giver, and the receiver recalibrated under the GREEDY message law (X06)."""
    E_greedy = {h: point(_argmax(d)) for h, d in E_soft.items()}
    R_recal = complete_receiver(prob, receiver_best_response(prob, E_greedy, True))
    return {"E_greedy": E_greedy, "R_recalibrated": R_recal,
            "J_soft": prob.value(E_soft, R_soft), "J_greedy_with_soft_receiver": prob.value(E_greedy, R_soft),
            "J_greedy_recalibrated": prob.value(E_greedy, R_recal)}


def importance_receiver_values(prob, E: dict, mu: dict, draws: dict) -> dict:
    """Receiver values from SAMPLED messages g ~ mu(. | h) with weights E/mu (X05).

    `draws[w]` lists the sampled gives for world w. A give with E > 0 and
    mu = 0 anywhere is a support failure and raises: nothing is clipped away.
    """
    for h, e in E.items():
        for g, pe in e.items():
            if pe > 0 and mu[h].get(g, 0.0) == 0.0:
                raise ValueError(f"proposal mu has no support for give {g} at giver key {h}")
    out: dict = {}
    for w in prob.worlds:
        n = len(draws[w])
        for g in draws[w]:
            wt = prob.prior[w] * E[prob.h[w]].get(g, 0.0) / mu[prob.h[w]][g] / n
            vals = out.setdefault((prob.p[w], g), {})
            for r in prob.returns[(w, g)]:
                vals[r] = vals.get(r, 0.0) + wt * prob.T[(w, g, r)]
    return out


def four_arm_analysis(j00, j10, j01, j11) -> dict:
    """Paired four-arm contrasts over source-deal clusters (X11), with simultaneous inference.

    Primary: J11 - J00. Interaction: J11 - J10 - J01 + J00. "The joint change beats each single
    change" needs BOTH J11 - J10 and J11 - J01 positive under a 2-comparison Bonferroni interval;
    the better single arm is never picked on the same data and used as the comparator.
    """
    arrs = [np.asarray(x, float) for x in (j00, j10, j01, j11)]
    n = len(arrs[0])
    if n < 2 or any(len(a) != n for a in arrs):
        raise ValueError("need paired arms over at least two clusters")
    a00, a10, a01, a11 = arrs

    def ci(x, z):
        m, s = float(x.mean()), float(x.std(ddof=1) / math.sqrt(n))
        return {"mean": m, "se": s, "ci": [m - z * s, m + z * s]}

    out = {"clusters": n, "primary_J11_minus_J00": ci(a11 - a00, 1.959963984540054),
           "interaction": ci(a11 - a10 - a01 + a00, 1.959963984540054),
           "J11_minus_J10_simultaneous": ci(a11 - a10, Z_SIMULTANEOUS_2),
           "J11_minus_J01_simultaneous": ci(a11 - a01, Z_SIMULTANEOUS_2)}
    out["joint_beats_each_single"] = (out["J11_minus_J10_simultaneous"]["ci"][0] > 0
                                      and out["J11_minus_J01_simultaneous"]["ci"][0] > 0)
    out["multiplicity"] = "Bonferroni over the two joint-vs-single comparisons; no chosen-best comparator"
    return out


def convention_aware_defender_status(proposal_weights: str | None = None,
                                     validated_generative_sampler: str | None = None) -> dict:
    """X12: a convention-aware defence needs derived proposal/target weights or a validated sampler."""
    if proposal_weights is None and validated_generative_sampler is None:
        return {"status": "UNRESOLVED",
                "reason": "the native sooli sampler's uniform-exchange/tilt/rejection mixture exposes no proposal "
                          "weight (E005); multiplying network probabilities onto it is not an exact posterior"}
    return {"status": "READY_FOR_REVIEW", "proposal_weights": proposal_weights,
            "validated_generative_sampler": validated_generative_sampler}


def reweight_native_sooli_draws(*_args, **_kwargs):
    raise NotImplementedError("refused: the native sooli sampler has no proposal density to divide by; "
                              "derive proposal/target weights or validate a generative sampler first (X12)")
