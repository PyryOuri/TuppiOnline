"""Batched decision-time search for data generation (expert iteration).

G games advance in lockstep. At every unforced decision of every game, the
acting seat's observation is searched exactly as `search.Searcher` does it -
W hard-feasible worlds, every legal action played out by the blueprint for all
seats, optional solver tail - but all games' rollouts share one rollout
environment, so each rollout step is a single large forward pass.

Each searched decision yields a training row: the observation's features, the
legal mask, the W-averaged value of every legal action (acting team's view,
RETURN_SCALE units), and the chosen action. The main games play the searched
action (optionally with epsilon exploration).

    python -m tuppi_ai.bsearch --blueprint runs/bc_v1.pt --out runs/xi/v1 --hours 1
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import model as qmodel
from . import native
from .equity import Equity

ROOT = Path(__file__).resolve().parents[1]


class BatchedSearch:
    def __init__(self, blueprint, equity_table, games=128, worlds=16, dd_left=6, capacity=40000,
                 seed=0, device="mps", p_random_start=0.25):
        self.bp, self.w, self.dd, self.device = blueprint, worlds, dd_left, device
        enc = blueprint.encoder
        self.main = native.Env(games, seed, equity_table, p_random_start=p_random_start, encoder=enc)
        self.roll = native.Env(capacity, seed + 1, equity_table, single_deal=True, encoder=enc)
        for j in range(capacity):
            self.roll.deal(j).phase = native.PH_DONE
        self.rng = C.c_uint64(seed * 7 + 3)
        self.np_rng = np.random.default_rng(seed)

    def _forward(self, feat):
        with torch.no_grad():
            return self.bp(torch.from_numpy(feat).to(self.device)).cpu().numpy()

    def step(self, eps: float = 0.0, tie: float = 1e-6):
        """Search every main game's current decision, then play it. Returns rows.

        Ties within `tie` of the best value go to the blueprint's own action, so
        inert decisions keep the blueprint's (consistent) choice.
        """
        main, roll, w = self.main, self.roll, self.w
        feat, mask, seat, phase = main.observe()
        feat, mask, seat, phase = feat.copy(), mask.copy(), seat.copy(), phase.copy()
        bp_q = self._forward(feat)
        bp_act = np.where(mask == 1, bp_q, -np.inf).argmax(1)
        acts = bp_act.copy()
        roll.park_all()
        plans, firsts = [], []
        used = 0
        for g in range(main.n):
            legal = np.nonzero(mask[g])[0]
            k = len(legal)
            if k < 2 or used + w * k > roll.n:
                continue
            obs = native.observe(main.deal(g), int(seat[g]))
            for wi in range(w):
                roll.set_state_repeat(used + wi * k, native.sample_world(obs, self.rng), k)
            plans.append((g, used, legal))
            firsts.append(np.tile(legal, w))
            used += w * k
        total = np.zeros(roll.n)
        if used:
            idx = np.arange(used, dtype=np.int32)
            roll.step_live(idx, np.concatenate(firsts))
            live = np.zeros(roll.n, dtype=bool)
            live[:used] = True
            self._collect(total, live)
            while live.any():
                if self.dd:
                    roll.dd_finish(self.dd)
                    self._collect(total, live)
                    if not live.any():
                        break
                f, m, idx = roll.observe_live()
                q = self._forward(f)
                roll.step_live(idx, np.where(m == 1, q, -np.inf).argmax(1))
                self._collect(total, live)
        rows = []
        for g, off, legal in plans:
            vals = total[off:off + w * len(legal)].reshape(w, len(legal)).mean(0)
            sign = 1.0 if (seat[g] & 1) == 0 else -1.0
            vals = sign * vals * qmodel.RETURN_SCALE
            bp_i = int(np.nonzero(legal == bp_act[g])[0][0])
            best_i = int(np.argmax(vals))
            if vals[bp_i] >= vals[best_i] - tie:
                best_i = bp_i
            best = int(legal[best_i])
            acts[g] = best
            v = np.zeros(native.NUM_ACTIONS, dtype=np.float32)
            v[legal] = vals
            rows.append((feat[g], mask[g], v, best, int(bp_act[g]), int(phase[g])))
        explore = self.np_rng.random(main.n) < eps
        if explore.any():
            noise = self.np_rng.random((int(explore.sum()), native.NUM_ACTIONS)) * mask[explore]
            acts[explore] = noise.argmax(1)
        main.step(acts.astype(np.int32))
        return rows

    def _collect(self, total, live):
        done = self.roll.done.astype(bool) & live
        total[done] = self.roll.delta0[done]
        live &= ~done


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--blueprint", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--games", type=int, default=128)
    p.add_argument("--worlds", type=int, default=16)
    p.add_argument("--dd", type=int, default=6)
    p.add_argument("--eps", type=float, default=0.02)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--shard-rows", type=int, default=50000)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    bp = qmodel.load(args.blueprint, device)
    eq = Equity.load(ROOT / "runs" / "equity_incumbent.json")
    bs = BatchedSearch(bp, eq.table, games=args.games, worlds=args.worlds, dd_left=args.dd,
                       seed=args.seed, device=device)
    buf, shard, t0, total_rows = [], 0, time.time(), 0
    agree = 0
    while time.time() - t0 < args.hours * 3600:
        rows = bs.step(args.eps)
        buf.extend(rows)
        agree += sum(r[3] == r[4] for r in rows)
        if len(buf) >= args.shard_rows:
            f = np.packbits(np.array([r[0] for r in buf]), axis=1)
            m = np.packbits(np.array([r[1] for r in buf]).astype(bool), axis=1)
            np.savez(args.out / f"shard_{args.seed:03d}_{shard:04d}.npz", feat=f, mask=m,
                     val=np.array([r[2] for r in buf]), act=np.array([r[3] for r in buf], dtype=np.int16),
                     bp=np.array([r[4] for r in buf], dtype=np.int16), phase=np.array([r[5] for r in buf], dtype=np.int8))
            total_rows += len(buf)
            print(json.dumps({"t": round(time.time() - t0), "rows": total_rows,
                              "rows_per_s": round(total_rows / (time.time() - t0), 1),
                              "search_agrees_with_blueprint": round(agree / total_rows, 4)}), flush=True)
            buf, shard = [], shard + 1


if __name__ == "__main__":
    main()
