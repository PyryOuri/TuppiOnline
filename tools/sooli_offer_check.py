"""Were the bank's accepted soolis worth it? (tools/sooli_bank.py, tools/sooli_play_eval.py)

For every banked sooli: the realised accept value is its survival in a play
evaluation (--play: the JSON from sooli_play_eval.py, --key: which pairing)
as the soolaaja team's match-equity change; the decline value is the same
offer declined and played out (the other defender's heuristic offer, then the
clone greedy with the last 6 tricks solved). Reported by the offer search's
predicted gain, so the margin can be set where realised gains stay positive.

    python tools/sooli_offer_check.py --bank runs/sooli/bank_v1.pkl --play runs/sooli/play.json --key "heur | search:b=5"
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import pickle
from pathlib import Path

import numpy as np

from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.best import EQUITY, ROLLOUT
from tuppi_ai.equity import Equity

native.lib.tc_finish_with_tricks.argtypes = [C.POINTER(native.TcDeal), C.c_int]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--play", type=Path, required=True)
    parser.add_argument("--key", required=True)
    args = parser.parse_args()
    bank = pickle.loads(args.bank.read_bytes())
    survived = json.loads(args.play.read_text())[args.key]
    net = qmodel.load(ROLLOUT, "cpu")
    mlp = native.Mlp(net)
    eq = Equity.load(EQUITY)
    feat = np.zeros((1, native.feature_dim(net.encoder)), dtype=np.uint8)
    st = C.c_uint64(17)

    def value(d, winner, points, team):
        after = (C.c_uint8 * 2)()
        native.lib.tc_next_score(d.score, winner, points, after)
        v = eq.delta0((d.score[0], d.score[1]), (after[0], after[1]), d.dealer)
        return v if team == 0 else -v

    rows = []
    for row, alive in zip(bank, survived):
        offer = native.TcDeal.from_buffer_copy(row["offer"])
        team = offer.cur & 1
        declarer_team = offer.declarer & 1
        acc = value(offer, team if alive else declarer_team, 24, team)
        d = native.TcDeal.from_buffer_copy(offer)
        native.lib.tc_apply(d, native.ACT_SOOLI_DECLINE)
        while d.phase != native.PH_DONE:
            if d.phase in native.SOOLI_PHASES:
                native.lib.tc_apply(d, native.sooli_policy(native.observe(d, d.cur), st))
            elif d.phase == native.PH_PLAY and 13 - d.n_played // 4 <= 6:
                native.lib.tc_finish_with_tricks(d, native.dd_team0_tricks(d))
            else:
                native.encode(native.observe(d, d.cur), feat[0], net.encoder)
                q = mlp.forward(feat)[0]
                native.lib.tc_apply(d, max(native.legal(d), key=lambda a: q[a]))
        dec = value(d, d.winner_team, d.points, team)
        rows.append((row["gain"], acc - dec, alive))
    g = np.array(rows)
    print(f"{len(g)} accepted soolis, survival {g[:, 2].mean():.3f}, realised gain vs declining "
          f"{g[:, 1].mean():+.4f} +- {1.96 * g[:, 1].std() / len(g) ** 0.5:.4f}")
    for lo, hi in ((0.02, 0.05), (0.05, 0.1), (0.1, 0.2), (0.2, 9)):
        m = (g[:, 0] > lo) & (g[:, 0] <= hi)
        if m.any():
            print(f"  predicted ({lo}, {hi}]: n={m.sum():4d} survival {g[m, 2].mean():.2f} "
                  f"realised {g[m, 1].mean():+.3f} predicted {g[m, 0].mean():+.3f}")
    for margin in (0.02, 0.05, 0.08, 0.1, 0.15):
        m = g[:, 0] > margin
        print(f"  margin {margin}: accepts {m.sum():4d}, total realised gain per banked offer "
              f"{np.where(m, g[:, 1], 0).mean():+.4f}")


if __name__ == "__main__":
    main()
