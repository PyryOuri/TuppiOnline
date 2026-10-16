"""C1: analytical control variates for ordinary NOLO discards (IMPLEMENTATION_SPEC.md section 3).

Pure numerics only (NumPy); no engine or native import at module level, so the
proxy can be cross-checked in an isolated RESEARCH-environment oracle process.

Proxy (3.2). For one complete remaining layout (current holdings; played
cards are gone) and a candidate discard a: remove a from the root's hand (it
is not reassigned). In each suit sort the root's remaining ranks r_i and each
other seat's ranks q_ji (partner included) low to high, ace high. Round i
counts 1 iff at least one other seat has an i-th card and r_i exceeds every
available q_ji. L_a(w) is the sum over suits and G_a(w) = -(L_a(w) - L_a0(w)).
This is a within-suit "everyone ducks" liability, a proxy only: it ignores
cross-suit lead allocation and the unresolved current trick.

Estimator (3.3). Independent cheap and expensive batches from the same
sampler:  gap[a] = beta * mean_M(G_a) + mean_n(D_a - beta * G_a), with
D_a = Y_a - Y_a0 and a frozen scalar beta. For fixed beta this is unbiased
for E[D_a] whatever G is; Var = beta^2 Var(G_a)/M + Var(D_a - beta G_a)/n.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

ESTIMATOR_VERSION = "c1.fixed_beta.independent_batches.v1"
PROXY_VERSION = "c1.contested_duck_liability.v1"


# ---------------------------------------------------------------- proxy


def suit_ranks(mask: int, suit: int) -> list[int]:
    """Ascending rank indices 0..12 (2..A, ace high) of `mask` in one suit."""
    bits = (int(mask) >> (13 * suit)) & 0x1FFF
    return [r for r in range(13) if bits >> r & 1]


def contested_liability(root_mask: int, other_masks) -> int:
    """L: rounds the root's i-th lowest card wins against every other i-th lowest."""
    total = 0
    for suit in range(4):
        mine = suit_ranks(root_mask, suit)
        if not mine:
            continue
        theirs = [suit_ranks(m, suit) for m in other_masks]
        for i, r in enumerate(mine):
            contest = [q[i] for q in theirs if len(q) > i]
            if contest and r > max(contest):
                total += 1
    return total


def liabilities(hands, root: int, actions) -> np.ndarray:
    """L_a for every candidate discard a (card ids) in one layout (4 current masks)."""
    others = [int(hands[s]) for s in range(4) if s != root]
    mine = int(hands[root])
    out = np.empty(len(actions), dtype=np.float64)
    for j, a in enumerate(actions):
        if not mine >> a & 1:
            raise ValueError(f"card {a} is not in the root's hand")
        out[j] = contested_liability(mine & ~(1 << a), others)
    return out


def proxy_matrix(layouts, root: int, actions, ref_index: int) -> np.ndarray:
    """G[w, k] = -(L_ak(w) - L_a0(w)); the reference column is exactly 0."""
    rows = [liabilities(h, root, actions) for h in layouts]
    L = np.array(rows, dtype=np.float64).reshape(len(rows), len(actions))
    return -(L - L[:, [ref_index]])


# ---------------------------------------------------------------- estimator


@dataclass(frozen=True)
class GapEstimate:
    gaps: np.ndarray        # [K], reference column exactly 0
    mu_g: np.ndarray        # [K] cheap-batch proxy mean
    residual: np.ndarray    # [K] expensive-batch mean of D - beta G
    variance: np.ndarray    # [K] estimated A/M + B/n
    beta: float
    m: int
    n: int
    ref_index: int
    version: str = ESTIMATOR_VERSION


def estimate_gaps(g_cheap: np.ndarray, d_exp: np.ndarray, g_exp: np.ndarray, beta: float,
                  ref_index: int) -> GapEstimate:
    """The fixed-beta two-batch estimator; batches must be independent draws of one law."""
    gc, d, ge = (np.asarray(x, dtype=np.float64) for x in (g_cheap, d_exp, g_exp))
    if gc.ndim != 2 or d.ndim != 2 or d.shape != ge.shape or gc.shape[1] != d.shape[1]:
        raise ValueError("expected g_cheap [M,K], d_exp and g_exp [n,K]")
    if not (np.all(d[:, ref_index] == 0) and np.all(ge[:, ref_index] == 0) and np.all(gc[:, ref_index] == 0)):
        raise ValueError("reference column must be exactly zero in D and G")
    if not (np.isfinite(gc).all() and np.isfinite(d).all() and np.isfinite(ge).all() and math.isfinite(beta)):
        raise ValueError("nonfinite input")
    m, n = gc.shape[0], d.shape[0]
    if n < 1:
        raise ValueError("the expensive batch is empty")
    if m == 0 and beta != 0:
        raise ValueError("beta != 0 needs a cheap batch: without it the estimate is biased by -beta E[G]")
    mu = gc.mean(axis=0) if m else np.zeros(d.shape[1])
    resid = (d - beta * ge).mean(axis=0)
    gaps = beta * mu + resid
    if m > 1:
        a = beta * beta * gc.var(axis=0, ddof=1)
    else:  # one cheap draw: Var(G) cannot be estimated, so neither can the variance (unless beta = 0)
        a = np.zeros(d.shape[1]) if beta == 0 else np.full(d.shape[1], np.nan)
    b = (d - beta * ge).var(axis=0, ddof=1) if n > 1 else np.full(d.shape[1], np.nan)
    var = (a / m if m else 0.0) + b / n
    gaps[ref_index] = 0.0
    return GapEstimate(gaps, mu, resid, var, float(beta), m, n, ref_index)


def plain_gaps(d_exp: np.ndarray) -> np.ndarray:
    """The ordinary Monte Carlo gap estimate (beta = 0, no cheap batch)."""
    return np.asarray(d_exp, dtype=np.float64).mean(axis=0)


def select(gaps: np.ndarray) -> int:
    """First maximum in the original ordered legal actions (the reference gap is 0)."""
    g = np.asarray(gaps, dtype=np.float64)
    best = 0
    for i in range(1, len(g)):
        if g[i] > g[best]:
            best = i
    return best


def fit_beta(cases) -> dict:
    """Single frozen beta from separate development cases (3.3).

    `cases`: iterable of (D [n_c, K_c], G [n_c, K_c], ref_index). Covariance is
    centred within each case AND action (so between-hand strength differences
    cannot manufacture correlation), averaged within each case, then pooled
    with equal case weights. beta = 0 when the pooled proxy variance is 0.
    """
    num = den = 0.0
    used = 0
    for d, g, ref in cases:
        d = np.asarray(d, dtype=np.float64)
        g = np.asarray(g, dtype=np.float64)
        keep = [j for j in range(d.shape[1]) if j != ref]
        if d.shape[0] < 2 or not keep:
            continue
        dc = d[:, keep] - d[:, keep].mean(axis=0)
        gcn = g[:, keep] - g[:, keep].mean(axis=0)
        num += float(np.mean(dc * gcn))
        den += float(np.mean(gcn * gcn))
        used += 1
    beta = num / den if den > 0 else 0.0
    return {"beta": beta, "cases": used, "pooled_cov": num, "pooled_var_g": den,
            "weights": "equal per case; centred within case and action"}


def optimal_beta(slope: float, m: int, n: int) -> float:
    """Variance-optimal fixed beta for the two-batch estimator: slope * M / (M + n).

    d/dbeta [beta^2 Var(G)/M + Var(D - beta G)/n] = 0 gives
    beta* = (Cov(D, G) / Var(G)) * M / (M + n): the regression slope shrunk
    toward 0 because the cheap batch is finite. Freeze it only after (M, n)
    are fixed on planning data.
    """
    if m < 0 or n < 1:
        raise ValueError("batch sizes")
    return slope * m / (m + n) if m else 0.0


def component_variances(d_exp, g_exp, g_cheap, beta: float, ref_index: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-action A = beta^2 Var(G) and B = Var(D - beta G), reference excluded (planning data)."""
    d, ge, gc = (np.asarray(x, dtype=np.float64) for x in (d_exp, g_exp, g_cheap))
    keep = [j for j in range(d.shape[1]) if j != ref_index]
    pool_g = np.concatenate([ge[:, keep], gc[:, keep]]) if gc.size else ge[:, keep]
    a = beta * beta * pool_g.var(axis=0, ddof=1)
    b = (d[:, keep] - beta * ge[:, keep]).var(axis=0, ddof=1)
    return a, b


def allocate(a: np.ndarray, b: np.ndarray, cost_cheap: float, cost_exp: float, budget: float, *,
             n_min: int = 2, m_min: int = 0, n_max: int = 4096, m_max: int = 1 << 16) -> dict:
    """Integer (M, n) for a fixed budget minimising the WORST action's variance A/M + B/n.

    The continuous single-action optimum is M/n = sqrt(A cD / (B cG)); with
    several actions the conservative choice minimises the maximum over
    nonreference actions. Degenerate cases: A = 0 everywhere puts no weight on
    the cheap batch; B = 0 everywhere uses the minimum expensive batch.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if cost_cheap <= 0 or cost_exp <= 0 or budget < n_min * cost_exp:
        raise ValueError("costs must be positive and the budget must cover the minimum expensive batch")
    best = None
    n_hi = min(n_max, int(budget // cost_exp))
    for n in range(n_min, n_hi + 1):
        m = int((budget - n * cost_exp) // cost_cheap)
        m = max(m_min, min(m, m_max))
        if n * cost_exp + m * cost_cheap > budget + 1e-9:
            continue
        if np.all(a == 0):
            m = m_min
        with np.errstate(divide="ignore", invalid="ignore"):
            var = np.where(a > 0, a / max(m, 1e-300), 0.0) + b / n
        worst = float(np.max(var)) if var.size else 0.0
        if best is None or worst < best[0] - 1e-18:
            best = (worst, m, n)
    if best is None:
        raise ValueError("no feasible allocation")
    ratio = None
    if np.all(a > 0) and np.all(b > 0):
        ratio = [float(math.sqrt(ai * cost_exp / (bi * cost_cheap))) for ai, bi in zip(a, b)]
    return {"M": best[1], "n": best[2], "worst_variance": best[0], "continuous_ratio_per_action": ratio,
            "rule": "min over integer n of max_a (A_a/M + B_a/n) at fixed budget"}


def fit_beta_on_split(cases, registry, split: str = "FIT") -> dict:
    """`fit_beta` restricted to one split: `cases` are (parent_deal_id, D, G, ref_index) and every parent
    must be registered in `split` (records.SplitRegistry); anything else raises SplitLeakError (V08)."""
    cases = list(cases)
    for parent, _d, _g, _ref in cases:
        registry.check_record(parent, split)
    out = fit_beta([(d, g, ref) for _p, d, g, ref in cases])
    out["split"] = split
    out["parents"] = sorted({p for p, *_rest in cases})
    return out
