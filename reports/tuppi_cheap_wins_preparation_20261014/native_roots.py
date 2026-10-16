#!/usr/bin/env python3
"""Small native root fingerprints across contracts, partial tricks and modes."""
from __future__ import annotations
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import resource
import time

from bootstrap import activate


def roots(native):
    specs = [(0, 0, (0, 0), 0), (1, 0, (48, 0), 1), (0, 29, (0, 44), 0),
             (1, 31, (24, 0), 1), (0, 40, (0, 48), 2), (1, 44, (0, 0), 2)]
    specs += [(i % 2, 28 + 4 * (i % 3), (0, 0), i % 3) for i in range(8)]
    for index, (contract, played, score, mode) in enumerate(specs):
        rng = random.Random(f"cw-roots|{index}")
        deck = list(range(52))
        rng.shuffle(deck)
        hands = [sum(1 << c for c in deck[s*13:(s+1)*13]) for s in range(4)]
        d = native.new_deal(hands, index % 4, *score, ruleset=3)
        if played:
            while d.phase != native.PH_PLAY:
                legal = native.legal(d)
                if d.phase == native.PH_SHOW:
                    action = next(a for a in legal if (a-52)//52 == contract)
                elif d.phase == native.PH_SOOLI_OFFER:
                    action = native.ACT_SOOLI_DECLINE
                else:
                    raise AssertionError("Unexpected ordinary fixture phase")
                assert native.lib.tc_apply(C.byref(d), action) == 0
            while d.n_played < played:
                assert native.lib.tc_apply(C.byref(d), rng.choice(native.legal(d))) == 0
        obs = native.observe(d, d.cur)
        ids = native.legal(d)
        if not played:
            ids = [next(a for a in ids if (a-52)//52 == k) for k in (0, 1)]
        else:
            ids = ids[:4]
        yield index, obs, ids, 1024 if played >= 40 or index >= 12 else 32 if index >= 6 else 8, mode


def run():
    resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
    activate()
    import torch
    torch.set_num_threads(1)
    from candidates import agents, configure_native
    from tuppi_ai import native
    import os
    arm = os.environ.get("CW_ROOT_ARM", "baseline")
    configure_native(arm, serial=True)
    rows = []
    for index, obs, ids, worlds, mode in roots(native):
        agent = agents(arm, worlds=worlds, seed=index+1, seats=[obs.seat])[obs.seat]
        sr = agent.searcher
        if mode:
            sr.env.set_sooli(17, False, mode == 1, 0.3)
        before = time.perf_counter()
        values = sr.action_values(obs, ids)
        rows.append({"index": index, "worlds": worlds, "contract": int(obs.contract), "phase": int(obs.phase),
                     "played": int(obs.n_played), "mode": mode, "ids": ids,
                     "values": [float(v).hex() for v in values], "rng": sr.rng.value,
                     "observation_hash": hashlib.sha256(bytes(obs)).hexdigest(),
                     "wall_seconds": time.perf_counter()-before})
    return {"schema": "tuppi.cheap_wins.native_roots.v1", "arm": arm, "rows": rows,
            "library": str(native._LIB_PATH), "cpu_seconds": time.process_time(),
            "scope": "Fourteen synthetic ordinary roots; W1024 only on solver tails. No full-game strength or latency claim."}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
