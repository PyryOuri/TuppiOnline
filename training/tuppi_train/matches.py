"""Complete matches, and deal-level results weighted as a match weights them.

A bot's strength is its share of matches won. The deal-level figures used so far
(equity per deal from 0-0, or from the release evaluator's "uniform" scores) are
proxies whose weighting is arbitrary: a match of the scoring table's own deal
model lasts about 36 deals, 35% of them from 0-0 and 12% with a lead of 32 or
more; "uniform" plays 8% from 0-0 and 31% with such a lead.

Two measurements here:

- `play_matches`: whole matches in lockstep, in mirrored pairs (the same deals
  in the same order for as long as the two matches stay in step, the sides
  swapped). The share of matches won needs no scoring table. Cheap for plain
  networks on a GPU; too slow for a search.
- `match_scores`: scores for duplicate deals drawn as a match visits them.
  Summed over a match, the equity changes of its deals are exactly the result
  minus the starting equity, whatever table defines the equity (a wrong table
  costs precision, not correctness). So

      share of matches won - 1/2  =  deals per match  x  mean equity change per deal,

  the mean taken over deals at the scores, leads and dealers a match visits. The
  visits of the bots' own matches are not known in advance; those of a reference
  (the table's deal model, or measured matches of similar bots) are a first-order
  approximation, exact as the two sides become equal.

    python -m tuppi_train.matches --a <net> --b <net> --pairs 20000
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time

import numpy as np

from . import device, lockstep, symmetry, tn
from tuppi_ai import native

lib = tn.lib
TARGET = 52
LEVELS = 13   # lead levels 0 (0-0), 4, ..., 48


def model_visits(model, matches: int = 200000, seed: int = 1) -> tuple[np.ndarray, float]:
    """(expected deals per match at each lead level [13], deals per match) for matches of a
    `tuppi_ai.equity.DealModel` (deal outcomes that do not depend on the score), by simulation."""
    rng = np.random.default_rng(seed)
    pd, pv = np.array(list(model.points_given_dealer)), np.array(list(model.points_given_dealer.values()))
    po, ov = np.array(list(model.points_given_other)), np.array(list(model.points_given_other.values()))
    lead, level = np.zeros(matches, np.int64), np.zeros(matches, np.int64)
    dealer, alive = rng.integers(0, 2, matches), np.ones(matches, bool)
    visits = np.zeros(LEVELS)
    while alive.any():
        idx = np.flatnonzero(alive)
        np.add.at(visits, level[idx], 1)
        dealer_won = rng.random(len(idx)) < model.dealer_win
        points = np.where(dealer_won, rng.choice(pd, len(idx), p=pv), rng.choice(po, len(idx), p=ov))
        winner = np.where(dealer_won, dealer[idx], 1 - dealer[idx])
        same = (level[idx] == 0) | (winner == lead[idx])
        new = np.where(same, level[idx] + points // 4, 0)
        lead[idx] = np.where(same, winner, lead[idx])
        level[idx] = new
        alive[idx[new >= LEVELS]] = False
        dealer[idx] = 1 - dealer[idx]
    visits /= matches
    return visits, float(visits.sum())


def match_scores(base_deals: int, seed: int, visits: np.ndarray) -> np.ndarray:
    """A score per base deal drawn as a match visits them: lead level with probability
    proportional to `visits`, either team leading with probability 1/2. uint8 [base_deals, 2].
    In the duplicate design the dealer sits in team 0 and each side is team 0 in half of a base
    deal's games, so leading or trailing, dealing or not are all balanced."""
    rng = np.random.default_rng(seed)
    level = rng.choice(LEVELS, base_deals, p=np.asarray(visits, np.float64) / np.sum(visits))
    lead0 = rng.random(base_deals) < 0.5
    out = np.zeros((base_deals, 2), np.uint8)
    out[:, 0] = np.where(lead0, 4 * level, 0)
    out[:, 1] = np.where(lead0, 0, 4 * level)
    return out


def next_scores(score: np.ndarray, winner_team: np.ndarray, points: np.ndarray) -> np.ndarray:
    """The rising score after a deal (tc_next_score): from 0-0 the winner takes the points; the
    leading side adds to its lead; a win of the trailing side resets to 0-0. uint8 [n, 2]."""
    s = score.astype(np.int64)
    w = np.asarray(winner_team, np.int64)
    rows = np.arange(len(s))
    level = (s == 0).all(1)
    up = np.where(s[:, 0] > 0, 0, 1)
    out = np.zeros_like(s)
    grow = level | (w == up)
    out[rows[grow], w[grow]] = s[rows[grow], w[grow]] + np.asarray(points, np.int64)[grow]
    return np.minimum(out, 255).astype(np.uint8)


def _seeds(seed: int, pair: np.ndarray, deal: np.ndarray) -> np.ndarray:
    """One 64-bit seed per (pair, deal number): the two matches of a pair share it."""
    x = (np.uint64(seed) * np.uint64(0x9E3779B97F4A7C15) + pair.astype(np.uint64) * np.uint64(0xBF58476D1CE4E5B9)
         + deal.astype(np.uint64) * np.uint64(0x94D049BB133111EB))
    x ^= x >> np.uint64(31)
    return x | np.uint64(1)


def play_matches(env: "native.Env", choose_a, choose_b, pairs: int, seed: int, ruleset: int = 3, encoder: int = 2,
                 max_deals: int = 2000) -> dict:
    """`pairs` mirrored pairs of complete matches from 0-0, A's pair against B's: in the first
    match of a pair A is team 0, in the second team 1; both get the same first dealer and, deal
    number by deal number, the same hands and the same stream for the heuristics' draws.

    Returns `a_wins` int [pairs] (0, 1 or 2 of the pair's matches won by A), `deals` int [2 pairs],
    `visits` float [13] (deals per match at each lead level) and `telescope`, the largest
    |sum of a match's equity changes - (result - starting equity)|, which is 0 up to rounding."""
    n = 2 * pairs
    if n > env.n:
        raise ValueError("environment too small")
    with np.errstate(over="ignore"):
        pair = np.repeat(np.arange(pairs), 2)
        a_team = np.tile(np.int8([0, 1]), pairs)
        score = np.zeros((n, 2), np.uint8)
        first_dealer = np.repeat(np.random.default_rng(seed).integers(0, 4, pairs), 2).astype(np.uint8)
        deals = np.zeros(n, np.int64)
        winner = np.full(n, -1, np.int8)
        visits = np.zeros(LEVELS)
        total = np.zeros(n)                       # sum of team-0 equity changes of the match's deals
        buf = lockstep.Buffers(env, encoder)
        feat, mask = np.zeros((n, buf.fb), np.uint8), np.zeros((n, buf.mb), np.uint8)
        team, actions = np.zeros(n, np.int8), np.zeros(n, np.uint8)
        state = np.zeros(n, np.dtype(native.TcDeal))
        while True:
            live = np.flatnonzero(winner < 0)
            m = len(live)
            if m == 0:
                break
            if deals[live].max() >= max_deals:
                raise RuntimeError("a match did not end")
            np.add.at(visits, score[live].max(1) // 4, 1)
            sc = np.ascontiguousarray(score[live])
            dl = np.ascontiguousarray((first_dealer[live] + deals[live]) % 4, np.uint8)
            sd = np.ascontiguousarray(_seeds(seed, pair[live], deals[live]))
            if lib.tc_ls_begin_games(env._h, m, ruleset, sc.ctypes.data, dl.ctypes.data, sd.ctypes.data) != 0:
                raise RuntimeError("lockstep begin failed")
            buf.total[:m] = 0.0
            mine = a_team[live]
            while True:
                k = buf.observe(m, feat, mask, None, team)
                if k == 0:
                    break
                idx = buf.idx[:k]
                is_a = team[:k] == mine[idx]
                for side, choose in ((is_a, choose_a), (~is_a, choose_b)):
                    if side.all():
                        actions[:k] = choose(feat[:k], mask[:k], idx, team[:k])[0]
                    elif side.any():
                        sel = np.nonzero(side)[0]
                        actions[sel] = choose(feat[sel], mask[sel], idx[sel], team[sel])[0]
                buf.step(actions, k)
            games = np.arange(m, dtype=np.int32)
            lib.tc_ls_copy_states(env._h, games.ctypes.data, m, state.ctypes.data)
            total[live] += buf.total[:m]
            deals[live] += 1
            score[live] = next_scores(score[live], state["winner_team"][:m], state["points"][:m])
            ended = live[score[live].max(1) >= TARGET]
            winner[ended] = np.where(score[ended, 0] >= TARGET, 0, 1)
    a_won = (winner == a_team).astype(np.int64)
    return {"a_wins": a_won.reshape(pairs, 2).sum(1), "deals": deals, "visits": visits / n, "team0_total": total,
            "winner": winner, "first_dealer": first_dealer}


def win_rate(a_wins: np.ndarray) -> list[float]:
    """[share of matches won by A, 95% half-width] from the pairs' counts."""
    share = a_wins / 2.0
    return [float(share.mean()), float(1.96 * share.std(ddof=1) / np.sqrt(len(share)))]


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)
    p.add_argument("--pairs", type=int, default=20000)
    p.add_argument("--chunk", type=int, default=8192, help="pairs played at once")
    p.add_argument("--seed", type=int, default=20261128)
    p.add_argument("--sooli-play", choices=("solver", "heuristic"), default="heuristic")
    p.add_argument("--weighted-base", type=int, default=0,
                   help="also: this many duplicate base deals at the scores these matches visited, and the share of "
                        "matches the deal-level result implies")
    p.add_argument("--amp", default="off", choices=sorted(device.AMP))
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    dev = device.pick(a.device)
    device.setup(dev)
    tn.use_cpus(0)
    native.set_offer_model(None)
    table = Equity.load(EQUITY).table
    net_a, net_b = symmetry.load_net(a.a, dev), symmetry.load_net(a.b, dev)
    chunk = min(a.chunk, a.pairs)
    env = native.Env(2 * chunk, 1, table, single_deal=True, encoder=net_a.encoder)
    env.set_sooli(0, False, a.sooli_play == "heuristic", 0.0)
    ca = lockstep.TorchGreedy(net_a, dev, net_a.encoder, amp=device.AMP[a.amp])
    cb = lockstep.TorchGreedy(net_b, dev, net_b.encoder, amp=device.AMP[a.amp])
    t0, wins, deals, visits = time.perf_counter(), [], [], np.zeros(LEVELS)
    for start in range(0, a.pairs, chunk):
        m = min(chunk, a.pairs - start)
        r = play_matches(env, ca, cb, m, a.seed + start)
        wins.append(r["a_wins"]), deals.append(r["deals"])
        visits += r["visits"] * m / a.pairs
    wins, deals = np.concatenate(wins), np.concatenate(deals)
    share, half = win_rate(wins)
    out = {"a": a.a, "b": a.b, "pairs": a.pairs, "sooli_play": a.sooli_play, "matches_won": share, "ci95": half,
           "deals_per_match": float(deals.mean()), "visits": [round(float(v), 4) for v in visits],
           "seconds": round(time.perf_counter() - t0, 1)}
    if a.weighted_base > 0:
        env2 = native.Env(8 * min(4096, a.weighted_base), 1, table, single_deal=True, encoder=net_a.encoder)
        env2.set_sooli(0, False, a.sooli_play == "heuristic", 0.0)
        values, rng = [], C.c_uint64(a.seed + 1)
        for start in range(0, a.weighted_base, 4096):
            m = min(4096, a.weighted_base - start)
            values.append(lockstep.duplicate_eval(env2, ca, cb, m, 3, rng, net_a.encoder,
                                                  score=match_scores(m, a.seed + 7 + start, visits)))
        mean, h = lockstep.interval(np.concatenate(values))
        out.update(weighted_base_deals=a.weighted_base, equity_per_deal=mean, equity_ci95=h,
                   implied_matches_won=0.5 + mean * out["deals_per_match"], implied_ci95=h * out["deals_per_match"])
    print(json.dumps(out), flush=True)


if __name__ == "__main__":
    main()
