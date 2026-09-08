"""Work package P1: calibrate a generation host in one command.

Replaces the assumption in ``docs/database/phase7_charter.md`` §7.1 - that a
Skylake core delivers 0.35-0.50x of the M3 Max core every other figure was
measured on - with a measurement, and projects the T1 wall time from it.

    PYTHONPATH=src python work/phase7_planning/calibrate.py

It writes nothing outside a temporary directory and takes about six minutes.
``--quick`` shrinks the match-length sample and the parallel pilot; the
throughput comparison runs a fixed workload either way, because that is what
makes the ratio against the development machine meaningful.

The correctness gate comes first and is the only part that can fail: if the
trusted engine path does not reproduce authoritative play *on this host*, the
whole generation plan is invalid here and the rest of the numbers are
irrelevant. That check is the condition ``tuppi_engine.trusted`` states for
using it at all.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import statistics
import sys
import tempfile
import time

from tuppi_agents.improved_registry import improved_agents_for_seats
from tuppi_engine import (
    EnginePhase,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.serialization import action_to_data
from tuppi_engine.trusted import trusted_transitions
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore


REFERENCE = "partner_aware_lead_v2"

#: The comparison workload, fixed. Sections 1-3 always use this so the ratio
#: against the dev machine means something; --quick only shrinks sections 4-5.
COMPARISON_STREAMS = 6

#: Measured on the development machine (Apple M3 Max, CPython 3.14.2) **by this
#: script**, mean of two runs. They must come from this script and not from the
#: standalone benchmarks in this directory: those use different stream seeds,
#: and because the elided validation cost is O(match history), the speedup is a
#: function of how long the sampled matches happen to run. The standalone gate
#: draws longer matches and reports 11.1x; this workload draws shorter ones and
#: reports ~8.4x. Both are correct for their own workload, which is exactly why
#: a ratio is only meaningful against a fixed one.
MAC = {
    "authoritative_actions_per_second": 415.0,
    "trusted_actions_per_second": 3497.0,
    "trusted_deals_per_second": 64.0,
    "speedup": 8.45,
    "pilot_deals_per_second_per_worker": 43.2,
    # Pure reference self-play over 200 streams. NOT the same quantity as the
    # corpus pilot's 24.7 deals/match, which mixes in single-deal paired strata
    # and softened play; conflating them made the first draft of this script
    # report a 38% discrepancy that did not exist.
    "deals_per_match_mean": 33.1,
    "bytes_per_deal": 68.6,
}

T1_DEALS = 10_000_000


def host_facts() -> dict[str, object]:
    facts: dict[str, object] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python": sys.version.split()[0],
        "os_cpu_count": os.cpu_count(),
    }
    try:
        facts["usable_cpus"] = len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        facts["usable_cpus"] = os.cpu_count()
    if Path("/proc/cpuinfo").exists():
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                facts["cpu_model"] = line.split(":", 1)[1].strip()
                break
        text = Path("/proc/meminfo").read_text() if Path("/proc/meminfo").exists() else ""
        for line in text.splitlines():
            if line.startswith("MemTotal"):
                facts["memory_gb"] = round(int(line.split()[1]) / 1048576, 1)
                break
    else:
        for key, command in (
            ("cpu_model", ["sysctl", "-n", "machdep.cpu.brand_string"]),
            ("memory_bytes", ["sysctl", "-n", "hw.memsize"]),
        ):
            binary = shutil.which(command[0])
            if binary is None:
                continue
            try:
                value = subprocess.run(
                    command, capture_output=True, text=True, timeout=10, check=True
                ).stdout.strip()
            except (subprocess.SubprocessError, OSError):
                continue
            if key == "memory_bytes":
                facts["memory_gb"] = round(int(value) / 1073741824, 1)
            else:
                facts[key] = value
    return facts


def play(streams: int, deals: int, *, trusted: bool, trace: bool):
    """One fixed workload. Returns (actions, seconds, trace, per-deal seconds)."""

    recorded: list[object] = []
    per_deal: list[float] = []
    actions = 0
    started = time.perf_counter()
    context = trusted_transitions() if trusted else _Null()
    with context:
        for index in range(streams):
            stream = MatchStream.build(
                root_seed="calibrate-v1", stream_index=index, initial_dealer=index % 4
            )
            table = improved_agents_for_seats(REFERENCE)
            state = create_match(
                initial_score=MatchScore(0, 0),
                initial_dealer=stream.initial_dealer,
                match_ref=f"cal-{index:06d}",
            )
            deal_index = 0
            deal_started = time.perf_counter()
            deal_actions = 0
            while not state.terminal and deal_index < deals:
                if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                    state = begin_explicit_deal(
                        state, stream.deal(deal_index).explicit_deal(state.dealer)
                    )
                    deal_index += 1
                    deal_started, deal_actions = time.perf_counter(), 0
                    continue
                actor = state.current_actor
                observation = match_observation_for(state, actor)
                action = table[actor].choose_action(observation)
                if trace:
                    recorded.append((index, actor, action_to_data(action)))
                state = apply_match_action(state, action)
                actions += 1
                deal_actions += 1
                if state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE):
                    per_deal.append((time.perf_counter() - deal_started) / deal_actions)
            if trace:
                recorded.append((index, "final", (state.score.team0, state.score.team1)))
    return (actions, time.perf_counter() - started, recorded, per_deal)


class _Null:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> bool:
        return False


def match_lengths(count: int) -> list[int]:
    lengths = []
    with trusted_transitions():
        for index in range(count):
            stream = MatchStream.build(
                root_seed="calibrate-len-v1", stream_index=index, initial_dealer=index % 4
            )
            table = improved_agents_for_seats(REFERENCE)
            state = create_match(
                initial_score=MatchScore(0, 0),
                initial_dealer=stream.initial_dealer,
                match_ref=f"len-{index:06d}",
            )
            deal_index = 0
            while not state.terminal and deal_index < 512:
                if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                    state = begin_explicit_deal(
                        state, stream.deal(deal_index).explicit_deal(state.dealer)
                    )
                    deal_index += 1
                    continue
                actor = state.current_actor
                state = apply_match_action(
                    state, table[actor].choose_action(match_observation_for(state, actor))
                )
            lengths.append(deal_index)
    return lengths


def corpus_throughput(streams: int, workers: int) -> tuple[float, int, float]:
    """Real parallel generation rate: the number that actually predicts T1."""

    with tempfile.TemporaryDirectory(prefix="tuppi-calibrate-") as directory:
        output = Path(directory) / "pilot"
        started = time.perf_counter()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tuppi_corpus.runner",
                "generate",
                "--output",
                str(output),
                "--stream-stop",
                str(streams),
                "--shard-streams",
                str(max(1, streams // max(1, workers))),
                "--workers",
                str(workers),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "OMP_NUM_THREADS": "1"},
        )
        elapsed = time.perf_counter() - started
        if result.returncode != 0:
            sys.stderr.write(result.stdout + result.stderr)
            raise SystemExit("corpus generation failed; see output above")
        deals = 0
        for line in result.stdout.splitlines():
            if " deals in " in line:
                deals = int(line.split()[2])
        size = sum(path.stat().st_size for path in (output / "shards").glob("*.tdc"))
        return (deals / elapsed, deals, size / max(1, deals))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick",
        action="store_true",
        help="shrink the match-length sample and the pilot; the throughput "
        "comparison is unaffected",
    )
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--json", type=Path, default=None, help="also write results here")
    args = parser.parse_args()

    facts = host_facts()
    usable = int(facts["usable_cpus"] or 1)
    workers = args.workers or usable

    print("=" * 72)
    print("Tuppi generation-host calibration (work package P1)")
    print("=" * 72)
    for key, value in facts.items():
        print(f"  {key:24s} {value}")
    print()

    # --- 1. the gate ------------------------------------------------------
    print("1. CORRECTNESS GATE - trusted play must equal authoritative play")
    # Fixed at six streams whatever --quick says. The reference constants below
    # were measured on exactly this workload, and match length is heavy-tailed
    # enough that a three-stream sample runs ~2x faster per action - so a
    # shorter workload here would compare this host against a different
    # question and report a meaningless ratio.
    streams = COMPARISON_STREAMS
    _a, _b, auth_trace, _c = play(streams, 512, trusted=False, trace=True)
    _d, _e, fast_trace, _f = play(streams, 512, trusted=True, trace=True)
    identical = auth_trace == fast_trace
    print(f"   checkpoints compared : {len(auth_trace)}")
    print(f"   identical play       : {identical}")
    if not identical:
        print()
        print("   *** GATE FAILED. Do not generate a corpus on this host. ***")
        print("   The trusted engine path diverged from the authoritative one here.")
        return 1
    print("   -> PASS")
    print()

    # --- 2. single-core throughput ---------------------------------------
    # Timed separately from the gate and with tracing OFF. Serialising every
    # action costs the same absolute amount on both paths, so including it in
    # the timing would understate the speedup - the trusted path's own per-action
    # cost is ~9x smaller, so a fixed overhead weighs ~9x more heavily on it.
    auth_actions, auth_seconds, _, growth = play(
        streams, 512, trusted=False, trace=False
    )
    fast_actions, fast_seconds, _, _ = play(streams, 512, trusted=True, trace=False)
    auth_rate = auth_actions / auth_seconds
    fast_rate = fast_actions / fast_seconds
    fast_deals = fast_rate / 54.7
    ratio = fast_deals / MAC["trusted_deals_per_second"]
    print("2. SINGLE-CORE THROUGHPUT")
    print(f"   {'':22s} {'this host':>12s} {'dev Mac':>12s} {'ratio':>8s}")
    for label, here, there in (
        ("authoritative act/s", auth_rate, MAC["authoritative_actions_per_second"]),
        ("trusted act/s", fast_rate, MAC["trusted_actions_per_second"]),
        ("trusted deals/s", fast_deals, MAC["trusted_deals_per_second"]),
        ("speedup", fast_rate / auth_rate, MAC["speedup"]),
    ):
        print(f"   {label:22s} {here:12.1f} {there:12.1f} {here / there:7.2f}x")
    print()
    print(f"   => this host is {ratio:.2f}x the dev machine per core")
    if ratio >= 0.90:
        print("      (this looks like the development machine itself, or faster)")
    elif 0.35 <= ratio <= 0.50:
        print("      the charter assumed 0.35-0.50x for the Fedora box: CONFIRMED")
    else:
        direction = "faster" if ratio > 0.50 else "slower"
        print(f"      the charter assumed 0.35-0.50x: this host is {direction} than")
        print("      assumed, so §7.1's calendar needs replacing with the projection below")
    print()

    # --- 3. history growth ------------------------------------------------
    if len(growth) >= 20:
        head = statistics.mean(growth[:5]) * 1000
        tail = statistics.mean(growth[-5:]) * 1000
        print("3. PER-ACTION COST GROWTH WITHIN A MATCH (the quadratic term)")
        print(f"   first 5 deals {head:.3f} ms/action -> last 5 deals {tail:.3f} ms/action"
              f"  ({100 * (tail / head - 1):+.0f}%)")
        print()

    # --- 4. match length --------------------------------------------------
    lengths = sorted(match_lengths(40 if args.quick else 120))
    quant = lambda p: lengths[min(len(lengths) - 1, int(p * len(lengths)))]
    print("4. MATCH LENGTH (a property of the rules, not the host; informational)")
    print(f"   mean {statistics.mean(lengths):.1f}  median {quant(0.5)}"
          f"  p90 {quant(0.9)}  max {lengths[-1]}   (Mac mean {MAC['deals_per_match_mean']})")
    print()

    # --- 5. parallel generation, the number that predicts T1 -------------
    print(f"5. PARALLEL GENERATION ({workers} workers) - the T1 predictor")
    pilot_streams = (60 if args.quick else 150) * workers
    rate, deals, bytes_per_deal = corpus_throughput(pilot_streams, workers)
    per_worker = rate / workers
    print(f"   {deals} deals at {rate:.1f} deals/s ({per_worker:.1f} per worker)")
    print(f"   bytes per deal on disk: {bytes_per_deal:.1f}   (Mac {MAC['bytes_per_deal']})")
    print(f"   per-worker scaling vs Mac: {per_worker / MAC['pilot_deals_per_second_per_worker']:.2f}x")
    print()

    hours = T1_DEALS / rate / 3600
    print("=" * 72)
    print("PROJECTION")
    print("=" * 72)
    print(f"  T1 = 10M deals at {rate:.0f} deals/s  ->  {hours:.1f} hours"
          f"  ({T1_DEALS * bytes_per_deal / 1e9:.2f} GB)")
    if hours > 24:
        print("  Over a day. Either accept it, finish P5 (E2 ~35% + E3 ~27% + PyPy)")
        print("  first, or generate on the faster host - see the runbook §3.")
    else:
        print("  Under a day; P5's optimisation work is not a gate on T1.")
    print()
    print("  Replace docs/database/phase7_charter.md §7.1 with the table above.")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "host": facts,
                    "gate_identical_play": identical,
                    "checkpoints": len(auth_trace),
                    "authoritative_actions_per_second": auth_rate,
                    "trusted_actions_per_second": fast_rate,
                    "trusted_deals_per_second": fast_deals,
                    "speedup": fast_rate / auth_rate,
                    "per_core_ratio_vs_dev": ratio,
                    "workers": workers,
                    "parallel_deals_per_second": rate,
                    "parallel_deals_per_second_per_worker": per_worker,
                    "bytes_per_deal": bytes_per_deal,
                    "match_length_mean": statistics.mean(lengths),
                    "t1_projected_hours": hours,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"  wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
