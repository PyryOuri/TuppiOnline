"""N08 offline cost report: the adapter, measured on N07's completed position list.

Deliberately memoryless — a fresh adapter at every position — so what is timed is
the expensive case: a first decision that must build a support, search it and
verify the certificate. Plan replay costs a dictionary lookup and is covered by
the tests, not folded into these numbers where it would flatter them.

This is an offline cost report. It is not a claim that the adapter is suitable
for the live server.
"""

import json
import pathlib
import statistics
import sys
import time
from multiprocessing import get_context

from tuppi_agents.void_lead import void_seeking_agents
from tuppi_engine import EnginePhase, PlayCardAction, apply_action, observation_for
from tuppi_rules import card_to_code
from tuppi_nolo.adapter import construct_security_certified_agent
from tuppi_nolo.runner import SCREEN_SEED, deal_state, is_eligible
from tuppi_nolo.support import SupportBudget

OUT = pathlib.Path("work/nolo/n08")


def measure_deal(index):
    budget = SupportBudget()
    state = deal_state(SCREEN_SEED, index)
    reference = void_seeking_agents()
    rows = []
    while state.phase is EnginePhase.TRICK_PLAY:
        actor = state.current_actor
        observation = observation_for(state, actor)
        baseline = reference[actor].choose_action(observation)
        if is_eligible(observation, budget):
            agent = construct_security_certified_agent(actor, budget=budget)
            started = time.perf_counter()
            action = agent.choose_action(observation)
            elapsed = time.perf_counter() - started
            report = agent.security_report(observation)
            rows.append({
                "deal_index": index,
                "seat": actor,
                "trick_index": len(observation.completed_tricks),
                "remaining_tricks": 13 - len(observation.completed_tricks),
                "seconds": elapsed,
                "outcome": report["outcome"],
                "corrected": bool(report.get("corrected", False)),
                "claim": report.get("claim"),
                "plan_size": int(report.get("plan_size", 0)),
                "world_count": report.get("world_count"),
                "search_engine_transitions": int(report.get("search_engine_transitions", 0)),
                "verification_engine_transitions":
                    int(report.get("verification_engine_transitions", 0)),
                "baseline_action": card_to_code(baseline.card),
                "adapter_action": card_to_code(action.card),
            })
        state = apply_action(state, baseline)
    return rows


def quantiles(values):
    ordered = sorted(values)
    if not ordered:
        return {"p50": None, "p95": None, "max": None}
    return {
        "p50": statistics.median(ordered),
        "p95": ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))],
        "max": ordered[-1],
    }


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 256
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    started = time.monotonic()
    rows = []
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "cost_rows.jsonl").open("w", encoding="utf-8") as handle:
        with get_context("spawn").Pool(processes=workers) as pool:
            for done, batch in enumerate(
                pool.imap_unordered(measure_deal, range(deals)), start=1
            ):
                rows.extend(batch)
                for row in batch:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                print(f"[{done:>4}/{deals}] positions={len(rows)} "
                      f"elapsed={(time.monotonic() - started) / 60:.1f}m", flush=True)

    resolved = [r for r in rows if not r["outcome"].startswith("nolo_fallback")]
    fallbacks = [r for r in rows if r["outcome"].startswith("nolo_fallback")]
    corrections = [r for r in rows if r["corrected"]]
    report = {
        "positions": len(rows),
        "resolved": len(resolved),
        "fallbacks": len(fallbacks),
        "fallback_rate": len(fallbacks) / len(rows) if rows else 0.0,
        "fallbacks_by_reason": {
            reason: sum(1 for r in fallbacks if r["outcome"] == reason)
            for reason in sorted({r["outcome"] for r in fallbacks})
        },
        "outcomes": {
            outcome: sum(1 for r in rows if r["outcome"] == outcome)
            for outcome in sorted({r["outcome"] for r in rows})
        },
        "corrections": len(corrections),
        "distinct_deals_corrected": len({r["deal_index"] for r in corrections}),
        "latency_seconds_all": quantiles([r["seconds"] for r in rows]),
        "latency_seconds_resolved": quantiles([r["seconds"] for r in resolved]),
        "search_transitions": quantiles([r["search_engine_transitions"] for r in resolved]),
        "verification_transitions":
            quantiles([r["verification_engine_transitions"] for r in resolved]),
        "plan_sizes_on_corrections": quantiles([r["plan_size"] for r in corrections]),
        "wall_seconds": time.monotonic() - started,
        "workers": workers,
        "deals": deals,
        "memoryless": True,
    }
    (OUT / "cost.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
