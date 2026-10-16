"""CPU numerical reference, fixed Team-0 perspective. No engine or ML imports.

Q trace: Fan & Farina (2026), equations 3.2–3.3.
Not an optimiser; inputs must use one explicitly chosen policy/critic snapshot.
"""
import math


def masked_probabilities(logits, legal):
    if not legal or len(set(legal)) != len(legal):
        raise ValueError('nonempty unique legal actions required')
    if any(a < 0 or a >= len(logits) for a in legal):
        raise ValueError('action outside head')
    if any(not math.isfinite(logits[a]) for a in legal):
        raise ValueError('nonfinite legal logit')
    top = max(logits[a] for a in legal)
    weights = {a: math.exp(logits[a] - top) for a in legal}
    z = sum(weights.values())
    return tuple(weights.get(a, 0.0) / z for a in range(len(logits)))


def expected_value(probabilities, q):
    if len(probabilities) != len(q):
        raise ValueError('shape mismatch')
    if any(not math.isfinite(p) or p < 0 for p in probabilities):
        raise ValueError('invalid probability')
    if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-10):
        raise ValueError('probabilities must sum to one')
    if any(not math.isfinite(v) for p, v in zip(probabilities, q) if p):
        raise ValueError('nonfinite supported Q')
    return sum(p * v for p, v in zip(probabilities, q) if p)


def targets(rewards, selected_q, values, *, gamma=1.0, lam=0.95,
            terminal=True):
    """One contiguous trajectory segment; values includes the bootstrap row.

    End of segment cuts traces. True terminal additionally requires V_end=0.
    A deal boundary inside a match is NOT a terminal for match objectives.
    Every intervening seat/environment transition must be represented.
    Returns (Q targets, boosted advantages, V-only GAE advantages).
    """
    n = len(rewards)
    if n == 0 or len(selected_q) != n or len(values) != n + 1:
        raise ValueError('trajectory shape mismatch')
    if not 0 <= gamma <= 1 or not 0 <= lam <= 1:
        raise ValueError('invalid discount/trace')
    if not all(math.isfinite(x) for x in (*rewards, *selected_q, *values)):
        raise ValueError('nonfinite trajectory')
    if terminal and values[-1] != 0:
        raise ValueError('terminal must not bootstrap')
    tq, aq, av = [0.0]*n, [0.0]*n, [0.0]*n
    cq = cv = 0.0
    for t in reversed(range(n)):
        cq = rewards[t] + gamma*values[t+1] - selected_q[t] + gamma*lam*cq
        cv = rewards[t] + gamma*values[t+1] - values[t] + gamma*lam*cv
        tq[t] = selected_q[t] + cq
        aq[t] = tq[t] - values[t]
        av[t] = cv
    return tq, aq, av


def actor_advantages(team0_advantages, seats):
    if len(team0_advantages) != len(seats) or any(s not in range(4) for s in seats):
        raise ValueError('invalid actor seats')
    return [a if s % 2 == 0 else -a for a, s in zip(team0_advantages, seats)]


def clipped_surrogate(new_logp, old_logp, advantage, epsilon=0.2):
    if not 0 < epsilon < 1:
        raise ValueError('invalid clipping')
    ratio = math.exp(new_logp - old_logp)
    return min(ratio*advantage, max(1-epsilon, min(1+epsilon, ratio))*advantage)
