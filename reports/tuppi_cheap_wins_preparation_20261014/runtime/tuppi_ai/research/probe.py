"""Cross-library parity probes (A03, A01/A02 runtime identity), one library per process.

    python -m tuppi_ai.research.probe --library R0-parity --cases cases.json --out out.json

Each probe case is a native observation (TcObs record), ordered action ids,
W, the solver tail, the environment's sooli settings, the rollout chunk and a
scalar seed. The probe calls the ORIGINAL entrypoint `tc_search_world_values`
through the unmodified `tuppi_ai.native` wrapper and records every per-world
value as float64 bytes, the return status and the scalar RNG after the call.
In the research build it also calls `research_trace_search` and replays the
traced worlds through `research_evaluate_worlds` with the recorded
continuation stream, which must reproduce the original bitwise.

Agent sequences construct a named factory (`best` by default, unmodified) and
feed it a fixed list of legal observations, recording each chosen action,
its searched values and the searcher's RNG state after each call.
"""

from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import sys
import time


def _hex(arr) -> str:
    import numpy as np

    return np.ascontiguousarray(arr, dtype=np.float64).tobytes().hex()


def run(library: str, cases: dict) -> dict:
    from .native_api import LIBRARIES, ResearchLibrary, bind_native

    nat = bind_native(LIBRARIES[library])
    from .identity import import_identity, loaded_tuppi_libraries, native_identity
    from .ledger import count
    from .observation import tcobs_from_data

    from .. import model as qmodel
    from ..best import EQUITY, ROLLOUT
    from ..equity import Equity

    net = qmodel.load(ROLLOUT, "cpu")
    table = Equity.load(EQUITY).table
    mlp = nat.Mlp(net)
    research = ResearchLibrary() if library == "R0-parity" else None
    out = {"library": library, "identity": native_identity(), "imports": import_identity(),
           "mapped": loaded_tuppi_libraries(), "probes": [], "sequences": []}
    calls = 0
    for case in cases.get("probes", []):
        obs = tcobs_from_data(case["obs"])
        env = nat.Env(case.get("env_slots", 128 * 26), case.get("env_seed", 0), table, single_deal=True,
                      encoder=net.encoder)
        env.set_sooli(*case["sooli"])
        nat.set_rollout_chunk(case.get("chunk", 32))
        rng = C.c_uint64(case["seed"])
        row = {"id": case["id"]}
        t0, c0 = time.perf_counter(), time.process_time()
        try:
            per_world = nat.search_world_values(env, mlp, obs, case["actions"], case["w"], case["dd"], rng)
            row.update({"status": "ok", "per_world_hex_sha256": hashlib.sha256(_hex(per_world).encode()).hexdigest(),
                        "values_hex": _hex(per_world.mean(axis=0)), "rng_after": rng.value})
        except RuntimeError as exc:
            row.update({"status": f"error: {exc}", "rng_after": rng.value})
        row["wall_s"], row["cpu_s"] = time.perf_counter() - t0, time.process_time() - c0
        calls += 1
        if research is not None and row["status"] == "ok":
            env.set_sooli(*case["sooli"])
            r2 = C.c_uint64(case["seed"])
            ev, worlds = research.trace_search(env, mlp, obs, case["actions"], case["w"], case["dd"], r2)
            r3 = C.c_uint64(case["seed"])
            sampled = research.sample_worlds(env, obs, case["w"], r3)  # rng after the root worlds only
            cont = C.c_uint64(r3.value)
            ev2 = research.evaluate_worlds(env, mlp, obs, worlds, case["actions"], case["dd"], cont)
            row["research"] = {
                "trace_equals_original": hashlib.sha256(_hex(ev.per_world).encode()).hexdigest()
                == row["per_world_hex_sha256"] and r2.value == row["rng_after"],
                "sample_only_equals_trace": all(bytes(a) == bytes(b) for a, b in zip(sampled, worlds)),
                "explicit_equals_original": hashlib.sha256(_hex(ev2.per_world).encode()).hexdigest()
                == row["per_world_hex_sha256"],
                "explicit_cont_rng_equals_original_final": cont.value == row["rng_after"],
                "sampler_draws_only_rng": r3.value, "all_cells_valid": bool(ev.valid.all()),
                "row_status_counts": {str(k): int(v) for k, v in zip(*__import__("numpy").unique(
                    ev.row_status, return_counts=True))},
                "work": ev.work}
            calls += 2
        out["probes"].append(row)
    nat.set_rollout_chunk(32)
    searched_calls = []
    for seq in cases.get("sequences", []):
        from .lifecycle import AgentSpec, RecordingAgent, snapshot
        from .observation import observation_from_data

        spec = AgentSpec.of(seq.get("factory", "best"), seq["seat"], **seq.get("params", {}))
        agent = RecordingAgent(spec)
        rows = []
        for data in seq["observations"]:
            obs = observation_from_data(data)
            action = agent.choose_action(obs)
            snap = snapshot(agent, research)
            sr = agent.agent.searcher
            lv = agent.agent.last_values
            rows.append({"action": agent.history[-1]["action"],
                         "last_values_hex": None if lv is None else _hex([lv[k] for k in sorted(lv)]),
                         "scalar_rng": sr.rng.value,
                         "numpy_rng": hashlib.sha256(json.dumps(sr.np_rng.bit_generator.state,
                                                                sort_keys=True).encode()).hexdigest(),
                         "native_config": None if research is None else
                         {k: v for k, v in snap["searcher"]["native_config"].items() if k != "equity"}})
            if lv is not None:
                calls += 1
                searched_calls.append(f"{seq['id']}#{len(rows) - 1}")
        out["sequences"].append({"id": seq["id"], "spec": spec.spec_id, "calls": rows})
    count(native_search_calls=calls, probe_ids=[p["id"] for p in cases.get("probes", [])] + searched_calls)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True, choices=("B0-installed", "B0-source", "R0-parity"))
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    cases = json.loads(open(args.cases).read())
    result = run(args.library, cases)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=1, sort_keys=True)
    json.dump({"library": args.library, "probes": len(result["probes"])}, sys.stdout)


if __name__ == "__main__":
    main()
