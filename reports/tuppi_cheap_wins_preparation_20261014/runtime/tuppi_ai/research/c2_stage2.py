"""P.C2 stage 2 (research/c2_stage2_manifest.json): reach conditioning at an equal effective sample.

    python -m tuppi_ai.research.c2_stage2        (C2_S2_SMOKE=n for an n-deal pre-flight)
"""

from __future__ import annotations

import ctypes as C
import json
import os
import time

import numpy as np

from .identity import OUTPUT_DIR

MANIFEST = OUTPUT_DIR / "research" / "c2_stage2_manifest.json"
RESULT = OUTPUT_DIR / "logs" / "c2_screen_stage2.json"


def _pick(ids, values):
    best = 0
    for i in range(1, len(values)):
        if values[i] > values[best]:
            best = i
    return ids[best]


def accepted_worlds(research, env, tobs, clone, c2, n_target: int, rng, max_draws: int, batch: int = 64):
    """Sampler worlds whose clone predecessors all pass, in draw order, until n_target (or max_draws)."""
    seats = c2.predecessor_seats(tobs.dealer, tobs.n_shows)
    worlds, calls_all, draws = [], [], 0
    while len(worlds) < n_target and draws < max_draws:
        for w in research.sample_worlds(env, tobs, min(batch, max_draws - draws), rng):
            draws += 1
            calls = []
            for pos, s in enumerate(seats):
                bid = clone.bid(c2.precommit_observation(w, s, pos))
                calls.append((s, bid))
                if (bid - 52) // 52 == 1:
                    break
            if len(calls) == len(seats) and all((b - 52) // 52 == 0 for _s, b in calls):
                worlds.append(w)
                calls_all.append(calls)
                if len(worlds) == n_target:
                    break
    return worlds, calls_all, draws


def run(max_deals: int | None = None) -> dict:
    from .native_api import RESEARCH_LIB, ResearchLibrary, bind_native

    nat = bind_native(RESEARCH_LIB)
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, match_observation_for

    from ..best import EQUITY, best_agents
    from ..bridge import action_id, obs_from_player_observation
    from ..equity import Equity
    from . import c2_blind_bids as c2
    from .clone_policy import rollout_network
    from .ledger import count
    from .runner_v3 import bundle_seed, new_match
    from .streams import scalar_stream, shuffled_deck, stream_seed

    m = json.loads(MANIFEST.read_text())
    caps, ns = dict(m["caps"]), m["population"]["deck_namespace"]
    budget_cpu = caps["cpu_seconds"] - float(os.environ.get("C2_S2_SPENT", "0"))
    if max_deals:
        caps["max_source_deals"] = max_deals
    n_acc, max_draws, n_val = m["rejection"]["target_accepted"], m["rejection"]["max_draws"], m["validation"]["accepted_worlds"]
    research = ResearchLibrary()
    table = Equity.load(EQUITY).table
    net = rollout_network()
    mlp = nat.Mlp(net)
    clone = c2.ClonePredecessor(mlp, net.encoder)
    positions, deals, stopped = [], [], None
    c_start, t_start = time.process_time(), time.perf_counter()
    for i in range(caps["max_source_deals"]):
        spent_cpu, spent_wall = time.process_time() - c_start, time.perf_counter() - t_start
        if deals and (spent_cpu + spent_cpu / len(deals) > budget_cpu
                      or spent_wall + spent_wall / len(deals) > caps["wall_seconds"]):
            stopped = f"cap would be exceeded before source deal {i}"
            break
        dealer, seed = i % 4, bundle_seed(ns, i)
        live = best_agents(worlds=128, seed=seed, team_rollout=False)  # B0: the audited configuration (clone rollouts on every seat)
        state = begin_explicit_deal(new_match((0, 0), dealer, "research-c2s2"),
                                    ExplicitDeal(dealer=dealer, hands=shuffled_deck("deal", ns, i)))
        reached = []
        while state.phase.value == "SHOWING":
            seat = state.current_actor
            obs = match_observation_for(state, seat)
            action = live[seat].choose_action(obs)
            reached.append((obs, action_id(action)))
            state = apply_match_action(state, action)
        deals.append({"source": i, "dealer": dealer, "contract": state.active_deal.contract.value,
                      "bids": [(o.observing_seat, o.bids_locked, a) for o, a in reached]})
        for obs, live_bid in reached:
            k = obs.bids_locked
            if k == 0 or len(obs.legal_actions) < 2:
                continue
            tobs = obs_from_player_observation(obs)
            ids = [action_id(a) for a in obs.legal_actions]
            env = nat.Env(n_acc * len(ids), 0, table, single_deal=True, encoder=net.encoder)
            c0 = time.process_time()
            acc, calls, draws = accepted_worlds(research, env, tobs, clone, c2, n_acc,
                                                scalar_stream("test", "c2-s2", "R", i, k), max_draws)
            cont = lambda arm: C.c_uint64(stream_seed("test", "c2-s2", "cont", arm, i, k))  # noqa: E731
            vR = research.evaluate_worlds(env, mlp, tobs, acc, ids, 6, cont("R")).values
            rc_worlds = [c2.with_chosen_shows(w, c) for w, c in zip(acc, calls)]
            vRC = research.evaluate_worlds(env, mlp, tobs, rc_worlds, ids, 6, cont("RC")).values
            fworlds = research.sample_worlds(env, tobs, n_acc, scalar_stream("test", "c2-s2", "F", i, k))
            vF = research.evaluate_worlds(env, mlp, tobs, fworlds, ids, 6, cont("F")).values
            picks = {"live": live_bid, "F128c": _pick(ids, vF), "R128": _pick(ids, vR), "RC128": _pick(ids, vRC)}
            row = {"source": i, "seat": obs.observing_seat, "k": k, "legal": len(ids), "draws": draws,
                   "accepted": len(acc), "exclusion_rate": 1 - len(acc) / draws, "picks": picks,
                   "arm_cpu_s": time.process_time() - c0}
            distinct = [a for a in ids if a in set(picks.values())]
            if len(distinct) > 1:
                v0 = time.process_time()
                venv = nat.Env(n_val * len(distinct), 0, table, single_deal=True, encoder=net.encoder)
                vacc, vcalls, vdraws = accepted_worlds(research, venv, tobs, clone, c2, n_val,
                                                       scalar_stream("validation", "c2-s2", i, k), 4 * max_draws)
                vw = [c2.with_chosen_shows(w, c) for w, c in zip(vacc, vcalls)]
                y = research.evaluate_worlds(venv, mlp, tobs, vw, distinct, 6,
                                             C.c_uint64(stream_seed("validation", "c2-s2", "cont", i, k))).per_world
                li = distinct.index(live_bid)
                val = {"accepted": len(vacc), "draws": vdraws}
                for arm in ("F128c", "R128", "RC128"):
                    if picks[arm] == live_bid:
                        val[arm] = {"mean": 0.0, "se": 0.0, "same_as_live": True}
                    else:
                        d = y[:, distinct.index(picks[arm])] - y[:, li]
                        val[arm] = {"mean": float(d.mean()), "se": float(d.std(ddof=1) / np.sqrt(len(d))),
                                    "same_as_live": False}
                val["cpu_s"] = time.process_time() - v0
                row["validation"] = val
            positions.append(row)
    count(search_game_ids=[f"c2-s2#{d['source']}" for d in deals])
    return {"positions": positions, "deals": deals, "stopped_early": stopped,
            "total_cpu_s": time.process_time() - c_start, "total_wall_s": time.perf_counter() - t_start}


def analyse(res: dict) -> dict:
    pos, deals = res["positions"], res["deals"]
    out = {"source_deals": len(deals), "evaluated_positions": len(pos),
           "contracts": {c: sum(1 for d in deals if d["contract"] == c) for c in ("NOLO", "RAMI")},
           "exclusion_rate_mean": float(np.mean([p["exclusion_rate"] for p in pos])) if pos else None,
           "shortfalls": sum(1 for p in pos if p["accepted"] < 128)}
    for arm in ("F128c", "R128", "RC128"):
        diffs, ses, changed = [], [], 0
        for p in pos:
            v = p.get("validation", {}).get(arm)
            if p["picks"][arm] == p["picks"]["live"] or v is None:
                diffs.append(0.0)
                ses.append(0.0)
            else:
                changed += 1
                diffs.append(v["mean"])
                ses.append(v["se"])
        d, s = np.array(diffs), np.array(ses)
        per_deal = {}
        for p, x in zip(pos, diffs):
            per_deal[p["source"]] = per_deal.get(p["source"], 0.0) + x
        pdv = np.array([per_deal.get(dd["source"], 0.0) for dd in deals])
        out[arm] = {"changed_vs_live": changed, "mean_per_reached_call": float(d.mean()) if len(d) else None,
                    "se_across_positions": float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else None,
                    "per_deal_mean": float(pdv.mean()) if len(pdv) else None,
                    "per_deal_se": float(pdv.std(ddof=1) / np.sqrt(len(pdv))) if len(pdv) > 1 else None,
                    "significantly_better": int(np.sum((d - 1.96 * s > 0) & (s > 0))),
                    "significantly_worse": int(np.sum((d + 1.96 * s < 0) & (s > 0)))}
    for arm in ("R128", "RC128"):
        a = np.array([(p.get("validation", {}).get(arm, {}).get("mean", 0.0) if p["picks"][arm] != p["picks"]["live"] else 0.0)
                      - (p.get("validation", {}).get("F128c", {}).get("mean", 0.0) if p["picks"]["F128c"] != p["picks"]["live"] else 0.0)
                      for p in pos])
        out[f"{arm}_minus_F128c_control"] = {"mean": float(a.mean()) if len(a) else None,
                                             "se": float(a.std(ddof=1) / np.sqrt(len(a))) if len(a) > 1 else None}
    return out


def main() -> None:
    global RESULT
    smoke = os.environ.get("C2_S2_SMOKE")
    if smoke:
        RESULT = OUTPUT_DIR / "logs" / "c2_screen_stage2_smoke.json"
    res = run(int(smoke) if smoke else None)
    summary = analyse(res)
    RESULT.write_text(json.dumps({"manifest": str(MANIFEST), "run": {k: v for k, v in res.items()
                                                                     if k not in ("positions", "deals")},
                                  "summary": summary, "deals": res["deals"], "positions": res["positions"]},
                                 indent=1, default=str))
    print(json.dumps({"run": {k: v for k, v in res.items() if k not in ("positions", "deals")}, "summary": summary},
                     indent=1, default=str))


if __name__ == "__main__":
    main()
