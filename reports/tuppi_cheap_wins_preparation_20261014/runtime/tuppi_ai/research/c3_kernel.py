"""C3a: pure match-transition kernel solver and the proposed mode-state model (section 6).

A `Kernel` is sparse: for every nonterminal state x, a list of (y, P[x, y])
and the one-step probabilities r0[x] / r1[x] that team 0 / team 1 wins the
match. Then v = (I - P)^(-1) r0 is team 0's match-win probability.

Solvers: `solve_direct` (dense, small systems; residual and condition number
reported), `solve_bounds` (lower/upper value iteration from 0 and 1: exact
truncation bounds for a valid substochastic kernel; a gap that does not
contract is UNRESOLVED), `solve_exact` (Fractions, tiny systems, independent)
and `simulate` (Monte Carlo, independent). Nothing is smoothed, clipped or
given pseudocounts: an unobserved or invalid row makes the answer unresolved.

`MODEL_ID` names the proposed augmented model; it is NOT the literal B0
finite-seed process (see research/c3_state_sufficiency.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product

import numpy as np

MODEL_ID = "C3-marginal-RNG-mode-model-v1"
LITERAL_B0_ID = "B0 literal finite-seed process (persistent PRNG and settings history)"
MODES = ("C", "O", "P")
SCORES = [(0, 0)] + [(4 * lv, 0) for lv in range(1, 13)] + [(0, 4 * lv) for lv in range(1, 13)]


class Unresolved(RuntimeError):
    """The kernel cannot give an identified answer (invalid/unobserved row, no contraction)."""


@dataclass
class Kernel:
    states: list
    rows: dict                      # state -> list[(next_state, p)]
    r0: dict                        # state -> P(team 0 wins the match in one step)
    r1: dict = field(default_factory=dict)
    observed: dict | None = None    # state -> sample count (estimated kernels)

    def index(self) -> dict:
        return {s: i for i, s in enumerate(self.states)}

    def validate(self, tol: float = 1e-12) -> list[str]:
        problems = []
        known = set(self.states)
        for s in self.states:
            row = self.rows.get(s)
            if row is None:
                problems.append(f"missing row {s}")
                continue
            if self.observed is not None and self.observed.get(s, 0) == 0:
                problems.append(f"unobserved row {s}")
            total = sum(p for _y, p in row) + self.r0.get(s, 0.0) + self.r1.get(s, 0.0)
            if any(p < 0 for _y, p in row) or self.r0.get(s, 0) < 0 or self.r1.get(s, 0) < 0:
                problems.append(f"negative probability in {s}")
            if total > 1 + tol:
                problems.append(f"row {s} sums to {total} > 1")
            if any(y not in known for y, _p in row):
                problems.append(f"row {s} leaves the state space")
        return problems

    def matrices(self):
        idx = self.index()
        n = len(self.states)
        P = np.zeros((n, n))
        r = np.zeros(n)
        for s in self.states:
            for y, p in self.rows[s]:
                P[idx[s], idx[y]] += p
            r[idx[s]] = self.r0.get(s, 0.0)
        return P, r

    def solve_direct(self) -> dict:
        problems = self.validate()
        if problems:
            raise Unresolved("; ".join(problems[:5]))
        P, r = self.matrices()
        A = np.eye(len(r)) - P
        v = np.linalg.solve(A, r)
        return {"v": dict(zip(self.states, v.tolist())), "residual": float(np.max(np.abs(A @ v - r))),
                "condition": float(np.linalg.cond(A)), "method": "dense direct solve"}

    def solve_bounds(self, tol: float = 1e-12, max_iter: int = 200_000) -> dict:
        problems = self.validate()
        if problems:
            raise Unresolved("; ".join(problems[:5]))
        P, r = self.matrices()
        lo, hi = np.zeros_like(r), np.ones_like(r)
        prev_gap = math.inf
        stalled = 0
        for it in range(max_iter):
            lo, hi = r + P @ lo, r + P @ hi
            gap = float(np.max(hi - lo))
            if gap < tol:
                return {"lower": dict(zip(self.states, lo.tolist())), "upper": dict(zip(self.states, hi.tolist())),
                        "gap": gap, "iterations": it + 1, "method": "lower/upper value iteration"}
            stalled = stalled + 1 if gap >= prev_gap * (1 - 1e-15) else 0
            if stalled > 50:
                raise Unresolved(f"bounds do not contract (gap {gap:.3g} after {it + 1} iterations): "
                                 "a closed nonabsorbing class")
            prev_gap = gap
        raise Unresolved(f"bounds gap {gap:.3g} after {max_iter} iterations")

    def solve_exact(self) -> dict:
        """Gaussian elimination in Fractions (independent of NumPy; tiny kernels only)."""
        if self.validate():
            raise Unresolved("invalid kernel")
        idx = self.index()
        n = len(self.states)
        A = [[Fraction(int(i == j)) for j in range(n)] + [Fraction(self.r0.get(s, 0))] for i, s in
             enumerate(self.states)]
        for s in self.states:
            for y, p in self.rows[s]:
                A[idx[s]][idx[y]] -= Fraction(p)
        for c in range(n):
            piv = next((i for i in range(c, n) if A[i][c] != 0), None)
            if piv is None:
                raise Unresolved("singular system: a closed nonabsorbing class")
            A[c], A[piv] = A[piv], A[c]
            for i in range(n):
                if i != c and A[i][c] != 0:
                    f = A[i][c] / A[c][c]
                    A[i] = [a - f * b for a, b in zip(A[i], A[c])]
        return {"v": {s: A[i][n] / A[i][i] for i, s in enumerate(self.states)}, "method": "exact rational"}

    def simulate(self, start, n: int, rng: np.random.Generator, max_steps: int = 10_000) -> dict:
        wins = unfinished = 0
        for _ in range(n):
            s = start
            for _step in range(max_steps):
                u = rng.random()
                if u < self.r0.get(s, 0.0):
                    wins += 1
                    break
                u -= self.r0.get(s, 0.0)
                if u < self.r1.get(s, 0.0):
                    break
                u -= self.r1.get(s, 0.0)
                acc = 0.0
                for y, p in self.rows[s]:
                    acc += p
                    if u < acc:
                        s = y
                        break
            else:
                unfinished += 1
        p = wins / n
        return {"estimate": p, "se": math.sqrt(max(p * (1 - p), 1e-12) / n), "unfinished": unfinished}


def paired_difference(kb: Kernel, kc: Kernel) -> dict:
    """vC - vB = (I - PC)^(-1) [(rC - rB) + (PC - PB) vB] on a common state list."""
    if kb.states != kc.states:
        raise ValueError("kernels need one state list")
    PB, rB = kb.matrices()
    PC, rC = kc.matrices()
    vB = np.linalg.solve(np.eye(len(rB)) - PB, rB)
    diff = np.linalg.solve(np.eye(len(rC)) - PC, (rC - rB) + (PC - PB) @ vB)
    return dict(zip(kb.states, diff.tolist()))


# ---------------------------------------------------------------- the Tuppi match chain


def next_score(score, winner: int, points: int):
    s0, s1 = score
    if s0 == 0 and s1 == 0:
        return (points, 0) if winner == 0 else (0, points)
    up = 0 if s0 > 0 else 1
    if winner == up:
        return (s0 + points, 0) if up == 0 else (0, s1 + points)
    return (0, 0)


def match_kernel(model) -> Kernel:
    """Score x dealer chain (100 states) under one deal-outcome model (tuppi_ai.equity.DealModel).

    The dealer's team wins a deal with model.dealer_win; point laws depend on
    whether the dealer's team won. The dealer rotates after every deal.
    """
    states = [(sc, d) for sc in SCORES for d in range(4)]
    rows, r0, r1 = {}, {}, {}
    for sc, d in states:
        row: dict = {}
        a0 = a1 = 0.0
        dealer_team = d % 2
        for won_by_dealer, weight, law in ((True, model.dealer_win, model.points_given_dealer),
                                           (False, 1 - model.dealer_win, model.points_given_other)):
            winner = dealer_team if won_by_dealer else 1 - dealer_team
            for pts, p in law.items():
                nxt = next_score(sc, winner, pts)
                if max(nxt) >= 52:
                    if nxt[0] >= 52:
                        a0 += weight * p
                    else:
                        a1 += weight * p
                else:
                    key = (nxt, (d + 1) % 4)
                    row[key] = row.get(key, 0.0) + weight * p
        rows[(sc, d)] = sorted(row.items())
        r0[(sc, d)], r1[(sc, d)] = a0, a1
    return Kernel(states, rows, r0, r1)


def augmented_states() -> list:
    """(score, dealer, per-seat mode) - at most 100 * 3^4 = 8100 nominal states (proposed model)."""
    return [(sc, d, modes) for sc in SCORES for d in range(4) for modes in product(MODES, repeat=4)]


def reduce_mode(mode: str) -> str:
    """C and P are behaviourally equivalent for every decision of the pinned factory (see the report)."""
    return "O" if mode == "O" else "CP"


def estimate_kernel(transitions, states) -> Kernel:
    """Empirical kernel from transition records {state, next | None, absorbed: None | 0 | 1}; no smoothing."""
    counts: dict = {s: {} for s in states}
    wins0 = {s: 0 for s in states}
    wins1 = {s: 0 for s in states}
    n = {s: 0 for s in states}
    for t in transitions:
        s = t["state"]
        n[s] += 1
        if t["absorbed"] == 0:
            wins0[s] += 1
        elif t["absorbed"] == 1:
            wins1[s] += 1
        else:
            counts[s][t["next"]] = counts[s].get(t["next"], 0) + 1
    rows = {s: sorted((y, c / n[s]) for y, c in counts[s].items()) if n[s] else [] for s in states}
    return Kernel(list(states), rows, {s: (wins0[s] / n[s] if n[s] else 0.0) for s in states},
                  {s: (wins1[s] / n[s] if n[s] else 0.0) for s in states}, observed=n)


def bundle_bootstrap(transitions, states, start, reps: int, rng: np.random.Generator) -> dict:
    """Resample whole deck bundles (all rows and arms of a bundle together); report the numerical
    residual of each solve separately from the sampling interval."""
    bundles: dict = {}
    for t in transitions:
        bundles.setdefault(t["bundle"], []).append(t)
    keys = sorted(bundles)
    point = estimate_kernel(transitions, states).solve_direct()
    values, residuals, unresolved = [], [], 0
    for _ in range(reps):
        pick = rng.integers(0, len(keys), len(keys))
        sample = [t for i in pick for t in bundles[keys[i]]]
        try:
            sol = estimate_kernel(sample, states).solve_direct()
        except Unresolved:
            unresolved += 1
            continue
        values.append(sol["v"][start])
        residuals.append(sol["residual"])
    values = np.sort(np.array(values))
    return {"point": point["v"][start], "point_residual": point["residual"], "reps": reps,
            "unresolved_reps": unresolved,
            "ci95": [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))] if len(values) else None,
            "max_numerical_residual": float(max(residuals)) if residuals else None,
            "note": "sampling interval (bundle bootstrap) and numerical residual are reported separately"}


def direct_match_agreement(kernel_value: float, kernel_ci, direct_ci, tolerance: float) -> str:
    """Agreement needs BOTH intervals inside the tolerance of each other; wide overlap is not agreement."""
    lo = min(kernel_ci[0], direct_ci[0])
    hi = max(kernel_ci[1], direct_ci[1])
    if hi - lo <= 2 * tolerance and abs(kernel_value - 0.5 * (direct_ci[0] + direct_ci[1])) <= tolerance:
        return "agree"
    if kernel_ci[1] < direct_ci[0] - tolerance or kernel_ci[0] > direct_ci[1] + tolerance:
        return "disagree"
    return "unresolved"
