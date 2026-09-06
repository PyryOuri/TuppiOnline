"""Run both paths over the frozen list and record every difference."""
import json, pathlib, statistics, time
from tuppi_eval.deals import DealerPolicy, generate_base_deal
from tuppi_engine import (EnginePhase, ExplicitDeal, PlayCardAction, apply_action,
                          create_deal_state, observation_for)
from tuppi_rules import Contract, MatchScore, card_from_code, card_to_code
from tuppi_valuation.corpus import forced_show_action
from tuppi_nolo.cache import SecurityCache
from tuppi_nolo.certificates import CheckStatus
from tuppi_nolo.security import SecurityStatus, solve_security
from tuppi_nolo.support import SupportBudget

DATA = json.loads(pathlib.Path("work/nolo/n06/positions.json").read_text())

def rebuild(deal_index, prefix):
    base = generate_base_deal(root_seed=DATA["seed"], index=deal_index,
        dealer_policy=DealerPolicy.ROUND_ROBIN, initial_dealer=0,
        starting_score=MatchScore(0, 0))
    ref = f"nolo-n06:{deal_index}"
    state = create_deal_state(ExplicitDeal(dealer=base.dealer, hands=base.hands),
        starting_score=MatchScore(0, 0), match_ref=ref, deal_ref=f"{ref}/deal:0",
        deal_number=0, event_start_index=0)
    while state.phase is EnginePhase.SHOWING:
        o = observation_for(state, state.current_actor)
        state = apply_action(state, forced_show_action(o, Contract.NOLO))
    for code in prefix:
        state = apply_action(state, PlayCardAction(seat=state.current_actor,
                                                   card=card_from_code(code)))
    return state

def summarise(r):
    return {
        "status": r.status.value,
        "values": sorted((card_to_code(v.action.card), v.security_value)
                         for v in r.root_values),
        "action": None if r.selected_action is None else card_to_code(r.selected_action.card),
        "verify": None if r.verification is None else r.verification.status.value,
        "tx": r.search_engine_transitions,
    }

rows, mismatches = [], []
for i, item in enumerate(DATA["positions"]):
    state = rebuild(item["deal"], item["prefix"])
    obs = observation_for(state, state.current_actor)
    t0 = time.perf_counter()
    plain = solve_security(obs, SupportBudget(), verification_budget=SupportBudget())
    t1 = time.perf_counter()
    cache = SecurityCache()
    fast = solve_security(obs, SupportBudget(), verification_budget=SupportBudget(), cache=cache)
    t2 = time.perf_counter()
    a, b = summarise(plain), summarise(fast)
    if (a["status"], a["values"], a["action"]) != (b["status"], b["values"], b["action"]):
        mismatches.append({"index": i, "plain": a, "cached": b, **item})
    rows.append({"index": i, "deal": item["deal"], "trick": item["trick"],
                 "plain": a, "cached": b, "cache": cache.diagnostics(),
                 "plain_s": t1 - t0, "cached_s": t2 - t1})
    if (i + 1) % 40 == 0:
        print(f"  {i+1}/{len(DATA['positions'])}", flush=True)

both = [r for r in rows if r["plain"]["status"] == "EXACT_COMPLETE"
        and r["cached"]["status"] == "EXACT_COMPLETE"]
excluded = [r for r in rows if r not in both]
p = sum(r["plain"]["tx"] for r in both)
c = sum(r["cached"]["tx"] for r in both)
out = {"positions": len(rows), "matched": len(both), "excluded": len(excluded),
       "mismatches": mismatches, "plain_tx": p, "cached_tx": c,
       "reduction_pct": 100 * (1 - c / p) if p else 0.0,
       "verify_failures": [r["index"] for r in rows if r["cached"]["verify"] not in (None, "EXACT_COMPLETE")],
       "median_plain_s": statistics.median(r["plain_s"] for r in both),
       "median_cached_s": statistics.median(r["cached_s"] for r in both),
       "rows": rows}
pathlib.Path("work/nolo/n06/comparison.json").write_text(json.dumps(out, indent=1))
print(f"\nmatched {len(both)}/{len(rows)}  excluded {len(excluded)}")
print(f"engine transitions: plain {p} -> cached {c}  ({out['reduction_pct']:+.1f}%)")
print(f"value/action mismatches: {len(mismatches)}   verify failures: {len(out['verify_failures'])}")
print(f"median wall time: plain {out['median_plain_s']*1000:.1f} ms  cached {out['median_cached_s']*1000:.1f} ms")
