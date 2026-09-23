"""Training data for a card-location belief network, from native self-play.

Each game's team 0 or team 1 (random per game) plays `--team-policy` (e.g. the
distilled search policy, standing in for the search agent) and the other team
plays `--opp-policy` (the incumbent clone). At every unforced decision the
actor's observation (encoder v2) is recorded together with, for every card that
is unseen by the actor, which other seat holds it (relative 1..3 -> 0..2; 255
for cards the actor can see: own hand or already played).

    python tools/gen_belief.py --out runs/belief/v1 --rows 8000000
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch

from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.equity import Equity

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--rows", type=int, default=8_000_000)
    p.add_argument("--games", type=int, default=4096)
    p.add_argument("--team-policy", type=Path, default=ROOT / "runs" / "xi1.pt")
    p.add_argument("--opp-policy", type=Path, default=ROOT / "runs" / "bc_v1.pt")
    p.add_argument("--eps", type=float, default=0.02)
    p.add_argument("--shard-rows", type=int, default=1_000_000)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    team_net = qmodel.load(args.team_policy, device)
    opp_net = qmodel.load(args.opp_policy, device)
    eq = Equity.load(ROOT / "runs" / "equity_incumbent.json")
    env = native.Env(args.games, args.seed, eq.table, p_random_start=0.25, encoder=2)
    rng = np.random.default_rng(args.seed)
    team_side = rng.integers(0, 2, args.games)  # which team plays team_net, per game
    F, T = [], []
    total, shard, t0 = 0, 0, time.time()
    while total < args.rows:
        feat, mask, seat, phase = env.observe()
        with torch.no_grad():
            x = torch.from_numpy(feat).to(device)
            qa = team_net(x).cpu().numpy()
            qb = opp_net(x).cpu().numpy()
        use_team = (seat & 1) == team_side
        q = np.where(use_team[:, None], qa, qb)
        acts = np.where(mask == 1, q, -np.inf).argmax(1)
        explore = rng.random(env.n) < args.eps
        if explore.any():
            acts[explore] = (rng.random((int(explore.sum()), native.NUM_ACTIONS)) * mask[explore]).argmax(1)
        keep = np.nonzero(mask.sum(1) > 1)[0]
        hands, _ = env.hands()
        tgt = np.full((len(keep), 52), 255, dtype=np.uint8)
        me = seat[keep]
        for r in (1, 2, 3):
            h = hands[keep, (me + r) & 3]
            bits = np.unpackbits(h.view(np.uint8).reshape(-1, 8), axis=1, bitorder="little")[:, :52]
            tgt[bits == 1] = r - 1
        F.append(np.packbits(feat[keep], axis=1))
        T.append(tgt)
        total += len(keep)
        env.step(acts.astype(np.int32))
        done = np.nonzero(env.done)[0]
        if len(done):
            team_side[done] = rng.integers(0, 2, len(done))
        if sum(len(t) for t in T) >= args.shard_rows or total >= args.rows:
            np.savez(args.out / f"shard_{args.seed:02d}_{shard:03d}.npz", feat=np.concatenate(F), loc=np.concatenate(T))
            print(f"{total} rows ({time.time() - t0:.0f}s)", flush=True)
            F, T, shard = [], [], shard + 1


if __name__ == "__main__":
    main()
