"""Speed baseline and move fingerprint for the best agent (docs/EFFICIENCY_PLAN.md, E0).

`run` plays a fixed set of project_target_v3 deals with the best agent on all
four seats through the authoritative engine, exactly as `tools/gen_game_db.py`
does (same per-deal reseeding, sooli options reset per deal), and reports:

* a fingerprint: SHA-256 over every decision's seat, phase, action and the
  exact bits of every searched value (`last_values`), so two builds that
  agree on it made the same moves from the same numbers;
* wall time per decision kind, total wall time and process CPU time (all
  threads).

`compare` runs `run` on two source trees in separate processes, alternating
the order, and reports medians and the speed ratio. A fingerprint mismatch
between the trees fails the comparison whatever the timings.

    python tools/profile_search.py run --worlds 128 --deals 12
    python tools/profile_search.py compare --a /path/to/baseline --b . --reps 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Fixed workloads: (worlds, deals). W=128 is the evaluation default, W=1024 the
# live server's setting (TuppiProject-current tuppi_server/match_runner.py).
WORKLOADS = {"w128": (128, 12), "w1024": (1024, 4)}


def _cpu() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


def _kind(o, native) -> str:
    if o.phase == native.PH_SHOW:
        return "bid"
    if o.phase == native.PH_PLAY:
        return f"play_{'rami' if o.contract == 1 else 'nolo'}_{'early' if o.n_played < 28 else 'late'}"
    return "sooli"


def _score(rng: random.Random) -> tuple[int, int]:
    """As tools/gen_game_db.py: 0-0 half the time, else a random reachable score."""
    if rng.random() < 0.5:
        return (0, 0)
    level = rng.randrange(1, 13)
    return (4 * level, 0) if rng.random() < 0.5 else (0, 4 * level)


def reseed(agents: dict, index: int) -> None:
    """As tools/gen_game_db.py (not imported: it puts its own tree first on sys.path)."""
    import ctypes as C

    import numpy as np

    for seat, agent in agents.items():
        for searcher in {id(agent.searcher): agent.searcher,
                         id(agent.show_searcher): agent.show_searcher}.values():
            if searcher is None:
                continue
            seed = (index * 4 + seat) * 2654435761 + 12345
            searcher.rng = C.c_uint64(seed & (2**64 - 1))
            searcher.np_rng = np.random.default_rng(seed)
            searcher.env.set_sooli(0, False, False, 0.0)


def run(worlds: int, deals: int, seed: str, chunk: int, start: int = 0) -> dict:
    import torch

    torch.set_num_threads(1)
    from tuppi_ai import native
    from tuppi_ai.best import best_agents
    from tuppi_ai.bridge import obs_from_player_observation
    from tuppi_engine import (ExplicitDeal, action_to_data, apply_match_action, begin_explicit_deal,
                              create_match, match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    native.set_rollout_chunk(chunk)
    agents = best_agents(worlds=worlds, seed=0)
    fp = hashlib.sha256()
    kinds: dict[str, list[float]] = {}
    n_decisions = 0
    wall0, cpu0 = time.perf_counter(), _cpu()
    with trusted_transitions():
        for index in range(start, start + deals):
            rng = random.Random(f"{seed}|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer = index % 4
            score = _score(rng)
            match = create_match(initial_score=MatchScore(*score), initial_dealer=dealer,
                                 match_ref=f"profile-{index}", ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
            reseed(agents, index)
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                observation = match_observation_for(state, seat)
                kind = _kind(obs_from_player_observation(observation), native)
                t0 = time.perf_counter()
                action = agents[seat].choose_action(observation)
                dt = time.perf_counter() - t0
                values = agents[seat].last_values
                if values is not None:  # forced moves and heuristic decisions are not timed as searches
                    kinds.setdefault(kind, []).append(dt)
                vals = "-" if values is None else ",".join(f"{k}:{float(v).hex()}" for k, v in sorted(values.items()))
                fp.update(f"{index}|{seat}|{observation.phase.value}|{json.dumps(action_to_data(action), sort_keys=True)}|{vals}\n".encode())
                n_decisions += 1
                state = apply_match_action(state, action)
    wall, cpu = time.perf_counter() - wall0, _cpu() - cpu0
    lib = Path(native.__file__).resolve().parents[1] / "native" / "libtuppi.dylib"
    return {
        "worlds": worlds, "deals": deals, "seed": seed, "chunk": chunk, "start": start,
        "src": str(Path(native.__file__).resolve().parents[1]),
        "libtuppi_sha256": hashlib.sha256(lib.read_bytes()).hexdigest(),
        "decisions": n_decisions, "fingerprint": fp.hexdigest(),
        "wall_s": round(wall, 3), "cpu_s": round(cpu, 3),
        "kinds": {k: {"n": len(v), "total_s": round(sum(v), 3), "mean_ms": round(1000 * statistics.fmean(v), 2)}
                  for k, v in sorted(kinds.items())},
    }


def _run_in(src: Path, args: list[str]) -> dict:
    """One `run` in a fresh process importing tuppi_ai from `src`."""
    env = dict(os.environ, PYTHONPATH=str(src))
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "profile_search.py"), "run", "--json", *args],
                         env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def compare(a: Path, b: Path, reps: int, workloads: list[str], chunk: int, seed: str) -> dict:
    report = {"a": str(a), "b": str(b), "reps": reps, "workloads": {}}
    for name in workloads:
        worlds, deals = WORKLOADS[name]
        args = ["--worlds", str(worlds), "--deals", str(deals), "--chunk", str(chunk), "--seed", seed]
        rows = {"a": [], "b": []}
        for rep in range(reps):
            order = ("a", "b") if rep % 2 == 0 else ("b", "a")
            for side in order:
                r = _run_in(a if side == "a" else b, args)
                rows[side].append(r)
                print(f"{name} rep {rep} {side}: wall {r['wall_s']:.2f}s cpu {r['cpu_s']:.2f}s "
                      f"fp {r['fingerprint'][:12]}", file=sys.stderr, flush=True)
        fps = {side: {r["fingerprint"] for r in rs} for side, rs in rows.items()}
        if not rows["a"] or not rows["b"]:
            raise RuntimeError("no runs")
        same = len(fps["a"]) == 1 and fps["a"] == fps["b"]
        summary = {"fingerprints_identical": same, "fingerprint_a": sorted(fps["a"]),
                   "fingerprint_b": sorted(fps["b"]), "decisions": rows["a"][0]["decisions"]}
        for metric in ("wall_s", "cpu_s"):
            ma = statistics.median(r[metric] for r in rows["a"])
            mb = statistics.median(r[metric] for r in rows["b"])
            summary[metric] = {"a_median": ma, "b_median": mb, "speedup_a_over_b": round(ma / mb, 3),
                               "a": [r[metric] for r in rows["a"]], "b": [r[metric] for r in rows["b"]]}
        kinds = {}
        for k in rows["a"][0]["kinds"]:
            ka = statistics.median(r["kinds"][k]["total_s"] for r in rows["a"])
            kb = statistics.median(r["kinds"].get(k, {"total_s": float("nan")})["total_s"] for r in rows["b"])
            kinds[k] = {"n": rows["a"][0]["kinds"][k]["n"], "a_total_s": ka, "b_total_s": kb,
                        "speedup": round(ka / kb, 3) if kb else None}
        summary["kinds_wall"] = kinds
        report["workloads"][name] = summary
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--worlds", type=int, default=128)
    r.add_argument("--deals", type=int, default=12)
    r.add_argument("--start", type=int, default=0)
    r.add_argument("--seed", default="profile-v3")
    r.add_argument("--chunk", type=int, default=32, help="native.set_rollout_chunk (32 = the live default)")
    r.add_argument("--json", action="store_true", help="print only the JSON result line")
    c = sub.add_parser("compare")
    c.add_argument("--a", type=Path, required=True, help="reference source tree")
    c.add_argument("--b", type=Path, required=True, help="candidate source tree")
    c.add_argument("--reps", type=int, default=5)
    c.add_argument("--workloads", default="w128,w1024")
    c.add_argument("--chunk", type=int, default=32)
    c.add_argument("--seed", default="profile-v3")
    c.add_argument("--out", type=Path)
    args = p.parse_args()
    if args.cmd == "run":
        result = run(args.worlds, args.deals, args.seed, args.chunk, args.start)
        print(json.dumps(result) if args.json else json.dumps(result, indent=1))
    else:
        report = compare(args.a.resolve(), args.b.resolve(), args.reps, args.workloads.split(","), args.chunk,
                         args.seed)
        text = json.dumps(report, indent=1)
        print(text)
        if args.out:
            args.out.write_text(text)
        if not all(w["fingerprints_identical"] for w in report["workloads"].values()):
            sys.exit("FINGERPRINT MISMATCH")


if __name__ == "__main__":
    main()
