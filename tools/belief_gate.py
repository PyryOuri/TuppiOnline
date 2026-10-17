"""Gate for play inference (strength step 2, 2026-10-16).

Question: if the worlds the search samples are weighted by how likely the
anchor policy (VRPO3) finds the other seats' actual past moves, do they
predict the hidden cards better than today's uniform worlds? No search runs
and nothing about strength is claimed; a belief that does not predict cards
better cannot help the search (docs/STATUS.md, the 2026-09-23 attempts).

For each game (cards, dealer, score, actions) a few card-play decisions are
taken; at each, the actor's observation; W uniform hard-feasible worlds
(tc_sample_world, as the search draws them); for every world the other
seats' past unforced decisions replayed in it (tc_history_rows, under the
world's own rules) and scored by VRPO3. Weight of a world =
prod_t [(1 - eps) * softmax(logits / T)[a_t] + eps / k_t]. Each config's
card-holder marginals are compared with the uniform ones by the negative
log-likelihood of every unseen card's true holder (lower is better).

    python tools/belief_gate.py --games games.jsonl --out gate.json
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch

from tuppi_ai import model as qmodel
from tuppi_ai import native

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [(t, eps) for t in (1.0, 2.0) for eps in (0.05, 0.2, 0.5)]
SEATS = ("opp", "all")
SMOOTH = 0.01  # the same floor on every marginal, uniform included


def positions(game: dict, per_game: int, rng: random.Random):
    """Replay a game; yield (deal state copy, observer) at chosen card-play decisions."""
    cards = game["cards"]
    hands = [sum(1 << c for c in cards[s * 13:(s + 1) * 13]) for s in range(4)]
    deal = native.new_deal(hands, game["dealer"], game["score"][0], game["score"][1], ruleset=3)
    owners = {c: s for s in range(4) for c in cards[s * 13:(s + 1) * 13]}
    chosen, steps = [], []
    for a in game["actions"]:
        if deal.soolaaja >= 0:
            return [], owners  # played soolis: not replayed by tc_history_rows
        if deal.phase == native.PH_PLAY and 4 <= deal.n_played <= 44 and len(native.legal(deal)) > 1:
            steps.append(TcCopy(deal))
        native.lib.tc_apply(C.byref(deal), a)
    if steps:
        idx = sorted(rng.sample(range(len(steps)), min(per_game, len(steps))))
        chosen = [steps[i] for i in idx]
    return chosen, owners


def TcCopy(deal):
    copy = native.TcDeal()
    C.memmove(C.byref(copy), C.byref(deal), C.sizeof(native.TcDeal))
    return copy


def score_position(deal, owners, net, dev, worlds: int, rng_state, buffers):
    seat = deal.cur
    obs = native.observe(deal, seat)
    played = {deal.play_card[i] for i in range(deal.n_played)}
    own = {c for c in range(52) if deal.hand[seat] >> c & 1}
    unseen = [c for c in range(52) if c not in own and c not in played]
    truth = np.array([(owners[c] - seat) % 4 - 1 for c in unseen])  # 0..2 = relative seats 1..3
    feat, mask, act = buffers
    holders = np.zeros((worlds, len(unseen)), np.int8)
    rows = {"opp": [], "partner": []}
    for i in range(worlds):
        world = native.sample_world(obs, rng_state)
        if world is None:
            raise RuntimeError("no world consistent with the observation")
        for j, c in enumerate(unseen):
            for r in (1, 2, 3):
                if world.hand[(seat + r) & 3] >> c & 1:
                    holders[i, j] = r - 1
                    break
        for key, seats in (("opp", (1 << ((seat + 1) & 3)) | (1 << ((seat + 3) & 3))), ("partner", 1 << ((seat + 2) & 3))):
            k = native.history_rows(world, seats, 2, feat, mask, act)
            if k < 0:
                raise RuntimeError("world inconsistent with the history")
            if k:
                rows[key].append((i, feat[:k].copy(), mask[:k].copy(), act[:k].copy()))
    logl = {}
    for key, items in rows.items():
        out = {cfg: np.zeros(worlds) for cfg in CONFIGS}
        if items:
            owner = np.concatenate([np.full(len(a), i) for i, _, _, a in items])
            f = torch.from_numpy(np.concatenate([f for _, f, _, _ in items])).to(dev)
            m = np.concatenate([m for _, _, m, _ in items]).astype(bool)
            a = np.concatenate([a for _, _, _, a in items])
            with torch.no_grad():
                logits = torch.cat([net(f[s:s + 65536]) for s in range(0, len(f), 65536)]).float().cpu().numpy()
            k = m.sum(1)
            for t, eps in CONFIGS:
                z = np.where(m, logits / t, -np.inf)
                z -= z.max(1, keepdims=True)
                p = np.exp(z); p /= p.sum(1, keepdims=True)
                taken = (1 - eps) * p[np.arange(len(a)), a] + eps / k
                np.add.at(out[(t, eps)], owner, np.log(taken))
        logl[key] = out

    def nll(weights):
        probs = np.zeros((3, len(unseen)))
        for r in range(3):
            probs[r] = (weights[:, None] * (holders == r)).sum(0)
        probs = (1 - SMOOTH) * probs + SMOOTH / 3
        return float(-np.log(probs[truth, np.arange(len(unseen))]).mean())

    result = {"seat": seat, "trick": deal.n_played // 4 + 1, "unseen": len(unseen),
              "uniform": nll(np.full(worlds, 1 / worlds))}
    for scope in SEATS:
        for cfg in CONFIGS:
            lw = logl["opp"][cfg] + (logl["partner"][cfg] if scope == "all" else 0)
            w = np.exp(lw - lw.max()); w /= w.sum()
            result[f"{scope}:T{cfg[0]:g}:e{cfg[1]:g}"] = {"nll": nll(w), "ess": float(1 / np.sum(w ** 2))}
    return result


def summary(rows, key):
    by = {}
    for row in rows:
        if key in row:
            by.setdefault(row["cluster"], []).append(row[key]["nll"] - row["uniform"])
    clusters = list(by.values())
    if not clusters:
        return None
    flat = [d for c in clusters for d in c]
    rng = np.random.default_rng(20261016)
    boots = [np.mean([d for i in rng.integers(0, len(clusters), len(clusters)) for d in clusters[i]]) for _ in range(4000)]
    ess = [row[key]["ess"] for row in rows if key in row]
    return {"paired_nll": float(np.mean(flat)), "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
            "positions": len(flat), "clusters": len(clusters), "median_ess": float(np.median(ess))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--worlds", type=int, default=1024)
    ap.add_argument("--per-game", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default=str(ROOT / "models" / "vrpo3_final.pt"))
    args = ap.parse_args()
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    net = qmodel.load(args.model, dev)
    assert net.encoder == 2
    # As the live bot samples (best.py: showing_fix with the team rollout): worlds
    # honour the showing-fallback restrictions, so every shown card was legal.
    native.set_showing_fix(True)
    games = [json.loads(line) for line in Path(args.games).read_text().splitlines() if line]
    if args.limit:
        games = games[:args.limit]
    rng, rng_state = random.Random(20261016), C.c_uint64(20261016)
    dim = native.feature_dim(2)
    buffers = (np.zeros((64, dim), np.uint8), np.zeros((64, native.NUM_ACTIONS), np.uint8), np.zeros(64, np.int32))
    rows, started, skipped = [], time.time(), 0
    for g, game in enumerate(games):
        chosen, owners = positions(game, args.per_game, rng)
        if not chosen:
            skipped += 1
            continue
        for deal in chosen:
            row = score_position(deal, owners, net, dev, args.worlds, rng_state, buffers)
            # Datasets: all-bot games; the expert's games seen by the expert (all
            # others bots: the matched case) or by a bot (the human among others).
            if game["source"] == "bot":
                row["dataset"] = "bot games"
            else:
                row["dataset"] = "expert games, expert observes" if row["seat"] == 0 else "expert games, bot observes (human among others)"
            row["cluster"] = f"{game['source']}:{game['deal']}"
            rows.append(row)
        if (g + 1) % 20 == 0:
            print(json.dumps({"games": g + 1, "positions": len(rows), "seconds": round(time.time() - started)}), flush=True)
    keys = [f"{scope}:T{t:g}:e{e:g}" for scope in SEATS for t, e in CONFIGS]
    report = {"worlds": args.worlds, "model": Path(args.model).name, "skipped_sooli_games": skipped,
              "positions": len(rows), "uniform_nll": float(np.mean([r["uniform"] for r in rows])), "datasets": {}}
    for dataset in sorted({r["dataset"] for r in rows}):
        sub = [r for r in rows if r["dataset"] == dataset]
        report["datasets"][dataset] = {"uniform_nll": float(np.mean([r["uniform"] for r in sub])),
                                       **{key: summary(sub, key) for key in keys}}
    Path(args.out).write_text(json.dumps({"report": report, "rows": rows}, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
