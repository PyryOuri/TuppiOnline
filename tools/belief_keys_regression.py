"""Worlds, per-world values and actions on the bid-belief work's 24 regression
positions, to compare two native libraries (Heidi fast plan, Stage 1 item 9).

    TUPPI_NATIVE_LIBRARY=<lib> python tools/belief_keys_regression.py dump OUT.json
    python tools/belief_keys_regression.py compare A.json B.json [--atol 1e-6]

The positions are those of TuppiAI-bid-belief tools/belief_regression_dump.py:
twelve policy-played v3 trick-play deals (test_belief_search.played_positions,
seed 77) and twelve bidding positions with 0-3 earlier NOLO bids; W=64, play
inference 8 (T 2, eps 0.5). Worlds must be byte-identical and actions equal;
per-world values may differ by Accelerate rounding up to the tolerance.
"""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import random
import sys
from pathlib import Path


def show_position(native, n_earlier: int, seed: int):
    rng = random.Random(seed)
    deck = list(range(52)); rng.shuffle(deck)
    hands = [sum(1 << c for c in deck[s * 13:(s + 1) * 13]) for s in range(4)]
    deal = native.new_deal(hands, rng.randrange(4), 0, 0, ruleset=3)
    for _ in range(n_earlier):
        nolo = [a for a in native.legal(deal) if 52 <= a < 104]
        assert native.lib.tc_apply(C.byref(deal), rng.choice(nolo)) == 0
    return deal


def dump(out: Path) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
    import numpy as np
    import test_belief_search as T
    from tuppi_ai import model as qmodel, native
    from tuppi_ai.equity import Equity
    policy = native.Mlp(qmodel.load(T.MODEL, "cpu"))
    rollout = native.Mlp(qmodel.load(T.MODEL.parent / "vrpo1_actor_0504.pt", "cpu"))
    table = Equity.load(T.MODEL.parent / "equity_incumbent.json").table
    env = native.Env(64 * 26, 1, table, single_deal=True, encoder=rollout.encoder)
    native.set_belief(env, policy, mult=8, temperature=2.0, eps=0.5)
    positions = [("play", d) for d, _ in T.played_positions(policy, 12, 77)]
    positions += [(f"show{n}", show_position(native, n, 500 + 10 * n + k)) for n in range(4) for k in range(3)]
    rows = {}
    native.belief_counters(reset=True)
    for i, (kind, deal) in enumerate(positions):
        obs = native.observe(deal, deal.cur)
        worlds = native.search_worlds(env, obs, 64, C.c_uint64(1000 + i))
        acts = native.legal(deal)
        vals = native.search_world_values(env, rollout, obs, acts, 64, 6, C.c_uint64(2000 + i))
        means = vals.mean(0)
        rows[f"{i:02d}-{kind}"] = {"worlds": [hashlib.sha256(bytes(w)).hexdigest()[:16] for w in worlds],
                                   "actions": [int(a) for a in acts], "values": vals.tolist(),
                                   "best": int(acts[int(np.argmax(means))]), "n_played": int(deal.n_played)}
    out.write_text(json.dumps({"library": str(native._LIB_PATH), "counters": native.belief_counters(),
                               "positions": rows}) + "\n")
    print(len(rows), "positions", native.belief_counters())


def compare(a: Path, b: Path, atol: float) -> int:
    A, B = json.loads(a.read_text())["positions"], json.loads(b.read_text())["positions"]
    assert A.keys() == B.keys()
    worst, report = 0.0, {}
    for key in A:
        x, y = A[key], B[key]
        same_worlds = x["worlds"] == y["worlds"]
        diff = max(abs(u - v) for ru, rv in zip(x["values"], y["values"]) for u, v in zip(ru, rv))
        worst = max(worst, diff)
        report[key] = {"worlds_identical": same_worlds, "best_equal": x["best"] == y["best"], "max_value_diff": diff}
    ok = all(r["worlds_identical"] and r["best_equal"] and r["max_value_diff"] <= atol for r in report.values())
    print(json.dumps({"passed": ok, "atol": atol, "max_value_diff": worst, "positions": report}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1] == "dump":
        dump(Path(sys.argv[2]))
    else:
        atol = float(sys.argv[sys.argv.index("--atol") + 1]) if "--atol" in sys.argv else 1e-6
        sys.exit(compare(Path(sys.argv[2]), Path(sys.argv[3]), atol))
