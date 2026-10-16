"""A03 disabled-mode parity: B0-installed vs B0-source vs R0-parity, in separate processes.

    python -m tuppi_ai.research.parity            # builds cases, runs 3 processes, writes the report

Probe cases come only from validated fixtures and their own decks (no new
deals): ordinary NOLO discards and leads, a three-card suffix, blind v3 bids
under the cold and both warm sooli-setting modes, the sooli offer, give and
play, an ordinary RAMI play after two declines, a smaller W and a different
rollout chunk. Every case keeps W <= 128 and one native search at a time.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .identity import OUTPUT_DIR

CASES = OUTPUT_DIR / "builds" / "parity_cases.json"
REPORT = OUTPUT_DIR / "builds" / "parity_report.json"
MODES = {"C": [0, False, False, 0.0], "O": [17, False, True, 0.3], "P": [17, False, False, 0.3]}


def _probe(pid, obs, *, sooli="C", w=128, dd=6, chunk=32, seed=None):
    from ..bridge import action_id, obs_from_player_observation
    from .observation import tcobs_to_data
    from .streams import stream_seed

    return {"id": pid, "obs": tcobs_to_data(obs_from_player_observation(obs)),
            "actions": [action_id(a) for a in obs.legal_actions], "w": w, "dd": dd, "chunk": chunk,
            "sooli": MODES[sooli], "sooli_mode": sooli,
            "seed": seed if seed is not None else stream_seed("test", "parity", pid)}


def build_cases() -> dict:
    from tuppi_engine import action_from_data, apply_match_action, match_observation_for, observation_to_data

    from .fixtures import RuleAgent, f03_hands, load_fixture, replay, walk
    from .clone_policy import CloneGreedyAgent

    def obs_of(fid, idx=0):
        _payload, cases, _truth = load_fixture(fid)
        return cases[idx].policy_observation()

    probes = [
        _probe("F02-discard-pos2", obs_of("F02", 0)),
        _probe("F02b-discard-pos3", obs_of("F02", 1)),
        _probe("F05-three-card-lead", obs_of("F05")),
        _probe("F01-bid-cold", obs_of("F01", 0), sooli="C"),
        _probe("F01-bid-offer-mode", obs_of("F01", 0), sooli="O"),
        _probe("F01-forehand-bid-play-mode", obs_of("F01", 1), sooli="P"),
        _probe("F03-give", obs_of("F03"), sooli="P"),
        _probe("F02-discard-pos2-W16", obs_of("F02", 0), w=16),
        _probe("F02-discard-pos2-chunk128", obs_of("F02", 0), chunk=128, seed=_probe("F02-discard-pos2",
                                                                                      obs_of("F02", 0))["seed"]),
    ]
    # States along fixture decks (no new deals): an early NOLO lead, the sooli offer, a
    # soolaaja play with a choice, and an ordinary RAMI play after two declines.
    _p, _c, t02 = load_fixture("F02")
    state = replay(t02, 0)
    for a in t02.action_history:
        o = match_observation_for(state, state.current_actor)
        if o.phase.value == "TRICK_PLAY" and not o.current_trick and len(o.legal_actions) >= 4:
            probes.append(_probe("F02deck-nolo-lead", o))
            break
        state = apply_match_action(state, action_from_data(a))
    _p, _c, t03 = load_fixture("F03")
    state = replay(t03, 0)
    for a in t03.action_history:
        o = match_observation_for(state, state.current_actor)
        if o.phase.value == "SOOLI_OFFER":
            probes.append(_probe("F03deck-offer", o, sooli="O"))
            break
        state = apply_match_action(state, action_from_data(a))
    hands = f03_hands()
    clones = {s: CloneGreedyAgent(s) for s in range(4)}
    from .fixtures import rami_first
    sooli_agents = {s: RuleAgent(s, clones[s], show=rami_first if s == 1 else None) for s in range(4)}
    _st, _h, o = walk(hands, sooli_agents,
                      stop=lambda st, ob: ob.phase.value == "SOOLI_PLAY" and ob.observing_seat == ob.soolaaja
                      and len(ob.legal_actions) >= 2)
    if o is not None:
        probes.append(_probe("F03deck-soolaaja-play", o, sooli="P"))
    decline = lambda ob: next(i for i, x in enumerate(ob.legal_actions) if not x.play_sooli)  # noqa: E731
    rami_agents = {s: RuleAgent(s, clones[s], show=rami_first if s == 1 else None, offer=decline) for s in range(4)}
    _st, _h, o = walk(hands, rami_agents,
                      stop=lambda st, ob: ob.phase.value == "TRICK_PLAY" and len(ob.legal_actions) >= 2)
    if o is not None:
        probes.append(_probe("F03deck-ordinary-rami-after-declines", o, sooli="C"))
    # A best-agent sequence: seat 3's first observations along F02's recorded deal.
    state = replay(t02, 0)
    seat3 = []
    for a in t02.action_history:
        if state.current_actor == 3:
            seat3.append(observation_to_data(match_observation_for(state, 3)))
        state = apply_match_action(state, action_from_data(a))
    sequences = [{"id": "best-seat3-F02deck", "factory": "best", "seat": 3,
                  "params": {"worlds": 128, "seed": 0}, "observations": seat3[:6]}]
    cases = {"schema": "tuppi.research.parity_cases.v1", "probes": probes, "sequences": sequences}
    CASES.parent.mkdir(parents=True, exist_ok=True)
    CASES.write_text(json.dumps(cases, indent=1, sort_keys=True))
    return cases


def compare(results: dict, cases: dict) -> dict:
    libs = list(results)
    by_id = {lib: {p["id"]: p for p in results[lib]["probes"]} for lib in libs}
    expected = {c["id"] for c in cases["probes"]}
    for lib in libs:  # an empty or partial result must fail, never pass vacuously
        if set(by_id[lib]) != expected:
            raise RuntimeError(f"{lib}: probe results {sorted(by_id[lib])} != cases {sorted(expected)}")
        got = {s["id"]: len(s["calls"]) for s in results[lib]["sequences"]}
        want = {s["id"]: len(s["observations"]) for s in cases["sequences"]}
        if got != want:
            raise RuntimeError(f"{lib}: sequence results {got} != cases {want}")
    rows = []
    for pid in by_id[libs[0]]:
        row = {"id": pid}
        ref = by_id["B0-source"][pid]
        for lib in libs:
            p = by_id[lib][pid]
            row[lib] = {"status": p["status"], "same_as_B0_source": all(p.get(k) == ref.get(k) for k in
                                                                        ("status", "per_world_hex_sha256",
                                                                         "values_hex", "rng_after"))}
        r = by_id["R0-parity"][pid].get("research", {})
        row["R0_research_exports"] = {k: r.get(k) for k in ("trace_equals_original", "sample_only_equals_trace",
                                                            "explicit_equals_original",
                                                            "explicit_cont_rng_equals_original_final",
                                                            "all_cells_valid", "row_status_counts")}
        row["work"] = r.get("work")
        rows.append(row)
    seqs = []
    for seq in results["B0-source"]["sequences"]:
        ref = seq["calls"]
        out = {"id": seq["id"], "calls": len(ref)}
        for lib in libs:
            other = next(s for s in results[lib]["sequences"] if s["id"] == seq["id"])["calls"]
            out[lib] = all(a[k] == b[k] for a, b in zip(ref, other)
                           for k in ("action", "last_values_hex", "scalar_rng", "numpy_rng")) and len(other) == len(ref)
        out["R0_native_config_trace"] = [c["native_config"] for c in
                                         next(s for s in results["R0-parity"]["sequences"]
                                              if s["id"] == seq["id"])["calls"]]
        seqs.append(out)
    chunk = next((r for r in rows if r["id"] == "F02-discard-pos2-chunk128"), None)
    base = by_id["B0-source"].get("F02-discard-pos2")
    chunk_same = (chunk is not None and base is not None and
                  by_id["B0-source"]["F02-discard-pos2-chunk128"]["per_world_hex_sha256"] == base["per_world_hex_sha256"])
    identities = {lib: {k: results[lib]["identity"][k] for k in ("path", "sha256", "struct_sizes", "mapped_tuppi_images")}
                  for lib in libs}
    all_probe_parity = all(r[lib]["same_as_B0_source"] for r in rows for lib in libs)
    all_research = all(all(r["R0_research_exports"][k] is True for k in
                           ("trace_equals_original", "sample_only_equals_trace", "explicit_equals_original",
                            "explicit_cont_rng_equals_original_final", "all_cells_valid"))
                       for r in rows if r["B0-source"]["status"] == "ok")
    return {"schema": "tuppi.research.parity_report.v1", "libraries": identities,
            "imports": {lib: results[lib]["imports"] for lib in libs},
            "probe_parity_all_libraries": all_probe_parity, "research_exports_all_equal": all_research,
            "sequence_parity": all(s[lib] for s in seqs for lib in libs),
            "chunk32_vs_chunk128_bitwise_equal_on_F02": {
                "value": chunk_same, "mlp_rows": (by_id["R0-parity"]["F02-discard-pos2"].get("research") or {})
                .get("work", {}).get("mlp_rows"),
                "note": "non-discriminating when mlp_rows is 0 (solver-only case); see chunk_check() for "
                        "network-using cases (builds/r0_api_v1/parity_report.json)"},
            "probes": rows, "sequences": seqs,
            "scope": "tested equivalence on these fixed cases only; not a universal proof"}


def main() -> None:
    libs = ("B0-installed", "B0-source", "R0-parity")
    for arg in sys.argv[1:]:
        if arg.startswith("--libs="):
            libs = tuple(arg.split("=", 1)[1].split(","))
    cases = build_cases()
    results = {}
    for lib in libs:
        out = CASES.parent / f"parity_{lib}.json"
        subprocess.run([sys.executable, "-m", "tuppi_ai.research.probe", "--library", lib, "--cases", str(CASES),
                        "--out", str(out)], check=True)
        results[lib] = json.loads(out.read_text())
    report = compare(results, cases)
    REPORT.write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps({k: report[k] for k in ("probe_parity_all_libraries", "research_exports_all_equal",
                                             "sequence_parity")}, indent=1))
    print(f"{len(cases['probes'])} probes, {sum(len(s['observations']) for s in cases['sequences'])} sequence calls")


if __name__ == "__main__" and "--chunk-check" not in sys.argv:
    main()


def chunk_check() -> dict:
    """Rollout-chunk invariance on cases that actually run the network (MLP rows > 0).

    Reuses the chunk-32 results recorded by `main` (same observations and
    seeds) and runs only the chunk-128 variants, on B0-source and R0-parity.
    """
    cases = json.loads(CASES.read_text())
    report = json.loads(REPORT.read_text())
    mlp_cases = [p for p in report["probes"] if p["work"] and p["work"]["mlp_rows"] > 0
                 and p["id"] in ("F02b-discard-pos3", "F02deck-nolo-lead")]
    chosen = [dict(c, id=c["id"] + "-chunk128", chunk=128) for c in cases["probes"]
              if c["id"] in {p["id"] for p in mlp_cases}]
    sub = {"schema": cases["schema"], "probes": chosen, "sequences": []}
    path = CASES.parent / "parity_chunk_cases.json"
    path.write_text(json.dumps(sub, indent=1, sort_keys=True))
    out = {}
    for lib in ("B0-source", "R0-parity"):
        res = CASES.parent / f"parity_chunk_{lib}.json"
        subprocess.run([sys.executable, "-m", "tuppi_ai.research.probe", "--library", lib, "--cases", str(path),
                        "--out", str(res)], check=True)
        base = {p["id"]: p for p in json.loads((CASES.parent / f"parity_{lib}.json").read_text())["probes"]}
        got = json.loads(res.read_text())["probes"]
        if len(got) != len(chosen):
            raise RuntimeError("chunk check: missing results")
        out[lib] = {p["id"]: {"mlp_rows_at_chunk32": next(m["work"]["mlp_rows"] for m in mlp_cases
                                                          if m["id"] == p["id"][:-len("-chunk128")]),
                              "per_world_bitwise_equal": p["per_world_hex_sha256"]
                              == base[p["id"][:-len("-chunk128")]]["per_world_hex_sha256"],
                              "rng_after_equal": p["rng_after"] == base[p["id"][:-len("-chunk128")]]["rng_after"]}
                    for p in got}
    report["chunk_invariance_on_mlp_cases"] = out
    report["chunk32_vs_chunk128_bitwise_equal_on_F02"] = {
        "value": report.get("chunk32_vs_chunk128_bitwise_equal_on_F02"),
        "non_discriminating": "F02 has five tricks left, so every rollout goes straight to the solver (0 MLP rows)"}
    REPORT.write_text(json.dumps(report, indent=1, sort_keys=True))
    return out


if __name__ == "__main__" and "--chunk-check" in sys.argv:
    print(json.dumps(chunk_check(), indent=1))
