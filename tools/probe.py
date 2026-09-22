"""Sanity probes of basic card play for a network, on positions from its own self-play.

    python tools/probe.py runs/pair1/latest.pt [more checkpoints...]
"""

from __future__ import annotations

import sys

import numpy as np
import torch

from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.equity import Equity
from tuppi_ai.evaluate import ROOT


def probe(net, games=512, steps=900, seed=3):
    eq = Equity.load(ROOT / "runs" / "equity_incumbent.json")
    env = native.Env(games, seed, eq.table, encoder=net.encoder)
    c = {k: [0, 0] for k in ("rami_last_win_cheapest", "rami_last_no_overtake_partner",
                              "nolo_duck_highest_under", "nolo_void_discard_highest",
                              "rami_last_cannot_win_plays_lowest")}
    for _ in range(steps):
        feat, mask, seat, phase = env.observe()
        with torch.no_grad():
            q = net(torch.from_numpy(feat)).numpy()
        acts = np.where(mask == 1, q, -np.inf).argmax(1)
        for i in range(games):
            if phase[i] != native.PH_PLAY or mask[i].sum() < 2:
                continue
            d = env.deal(i)
            pos = d.n_played & 3
            legal = np.nonzero(mask[i])[0]
            a = int(acts[i])
            if pos == 0:
                continue
            start = d.n_played - pos
            trick = [(d.play_seat[j], d.play_card[j]) for j in range(start, d.n_played)]
            led = trick[0][1] // 13
            best_seat, best = max(((s, cc) for s, cc in trick if cc // 13 == led), key=lambda t: t[1])
            partner_winning = (best_seat & 1) == (d.cur & 1)
            following = [x for x in legal if x // 13 == led]
            winners = [x for x in following if x > best]
            losers = [x for x in following if x < best]
            if d.contract == native.RAMI and pos == 3 and following:
                if not partner_winning and winners:
                    c["rami_last_win_cheapest"][0] += a == min(winners)
                    c["rami_last_win_cheapest"][1] += 1
                if partner_winning:
                    c["rami_last_no_overtake_partner"][0] += a == min(following)
                    c["rami_last_no_overtake_partner"][1] += 1
                if not winners and not partner_winning:
                    c["rami_last_cannot_win_plays_lowest"][0] += a == min(following)
                    c["rami_last_cannot_win_plays_lowest"][1] += 1
            if d.contract == native.NOLO and following and losers and pos == 3:
                c["nolo_duck_highest_under"][0] += a == max(losers)
                c["nolo_duck_highest_under"][1] += 1
            if d.contract == native.NOLO and not following:
                # Void: a common heuristic is to shed the highest card overall.
                c["nolo_void_discard_highest"][0] += (a % 13) == max(x % 13 for x in legal)
                c["nolo_void_discard_highest"][1] += 1
        env.step(acts.astype(np.int32))
    return {k: (round(v[0] / v[1], 3) if v[1] else None, v[1]) for k, v in c.items()}


if __name__ == "__main__":
    for path in sys.argv[1:]:
        net = qmodel.load(path) if path != "untrained" else qmodel.QNet(encoder=2).eval()
        print(path, probe(net))
