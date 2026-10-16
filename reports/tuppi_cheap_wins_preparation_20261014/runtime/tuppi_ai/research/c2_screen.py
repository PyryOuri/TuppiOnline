"""P.C2 stage 1 screen (research/c2_screen_manifest.json).

    python -m tuppi_ai.research.c2_screen        (C2_SCREEN_SMOKE=n for an n-deal pre-flight)

Natural v3 deals by the unmodified best agents, played through showing only.
At each reached blind bid with k >= 1 earlier bidders: F / R / RC on 64 worlds
with clone predecessors, and (first 6 positions) the predecessors' bids
recomputed by fresh W128 forks. Runs on R0-parity.
"""

from __future__ import annotations

import ctypes as C
import json
import os
import time

import numpy as np

from .identity import OUTPUT_DIR

MANIFEST = OUTPUT_DIR / "research" / "c2_screen_manifest.json"
RESULT = OUTPUT_DIR / "logs" / "c2_screen_stage1.json"


def _argmax(g) -> int:
    best = 0
    for i in range(1, len(g)):
        if g[i] > g[best]:
            best = i
    return best


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
    from .lifecycle import AgentSpec, RecordingAgent
    from .runner_v3 import bundle_seed, new_match
    from .streams import scalar_stream, shuffled_deck

    m = json.loads(MANIFEST.read_text())
    caps, ns = dict(m["caps"]), m["population"]["deck_namespace"]
    if max_deals:
        caps["max_source_deals"] = max_deals
    W, n_cal_pos, n_cal_worlds = m["evaluation"]["worlds_per_position"], 4, 6
    W_VAL = 256
    research = ResearchLibrary()
    table = Equity.load(EQUITY).table
    net = rollout_network()
    mlp = nat.Mlp(net)
    clone = c2.ClonePredecessor(mlp, net.encoder)
    positions, deals, stopped = [], [], None
    calibrated = 0
    c_start, t_start = time.process_time(), time.perf_counter()
    for i in range(caps["max_source_deals"]):
        spent_cpu, spent_wall = time.process_time() - c_start, time.perf_counter() - t_start
        if deals and (spent_cpu + spent_cpu / len(deals) > caps["cpu_seconds"]
                      or spent_wall + spent_wall / len(deals) > caps["wall_seconds"]):
            stopped = f"cap would be exceeded before source deal {i}"
            break
        dealer, seed = i % 4, bundle_seed(ns, i)
        hands = shuffled_deck("deal", ns, i)
        live = best_agents(worlds=128, seed=seed, team_rollout=False)  # B0: the audited configuration (clone rollouts on every seat)
        state = begin_explicit_deal(new_match((0, 0), dealer, "research-c2"), ExplicitDeal(dealer=dealer, hands=hands))
        reached = []
        c0 = time.process_time()
        while state.phase.value == "SHOWING":
            seat = state.current_actor
            obs = match_observation_for(state, seat)
            t0 = time.process_time()
            action = live[seat].choose_action(obs)
            reached.append((obs, action_id(action), time.process_time() - t0))
            state = apply_match_action(state, action)
        deals.append({"source": i, "dealer": dealer, "bids": [(o.observing_seat, o.bids_locked, a) for o, a, _c in reached],
                      "contract": None if state.active_deal.contract is None else state.active_deal.contract.value,
                      "showing_cpu_s": time.process_time() - c0})
        for obs, live_bid, live_cpu in reached:
            k = obs.bids_locked
            row = {"source": i, "seat": obs.observing_seat, "k": k, "live_bid": live_bid, "live_bid_cpu_s": live_cpu,
                   "legal": len(obs.legal_actions)}
            if k == 0 or len(obs.legal_actions) < 2:
                row["evaluated"] = False
                positions.append(row)
                continue
            tobs = obs_from_player_observation(obs)
            ids = [action_id(a) for a in obs.legal_actions]
            env = nat.Env(W * len(ids), 0, table, single_deal=True, encoder=net.encoder)
            worlds = research.sample_worlds(env, tobs, W, scalar_stream("test", "c2-screen", i, k))
            e0 = time.process_time()
            b = c2.evaluate(research, env, mlp, tobs, ids, worlds, predecessor=clone)
            gF, gR, gRC = b.conditional_gaps["F"], b.conditional_gaps["R"], b.conditional_gaps["RC"]
            row.update({"evaluated": True, "hits": b.hits, "W": W, "exclusion_rate": 1 - b.hits / W,
                        "eval_cpu_s": time.process_time() - e0,
                        "argmax": {"F": ids[_argmax(gF)],
                                   "R": None if gR is None else ids[_argmax(gR)],
                                   "RC": None if gRC is None else ids[_argmax(gRC)]},
                        "live_bid_in_F_argmax": ids[_argmax(gF)] == live_bid,
                        "max_abs_R_minus_F": None if gR is None else float(np.max(np.abs(gR - gF))),
                        "max_abs_RC_minus_R": None if gRC is None or gR is None else float(np.max(np.abs(gRC - gR))),
                        "regret_of_F_under_R": None if gR is None else float(gR[_argmax(gR)] - gR[_argmax(gF)]),
                        "regret_of_F_under_RC": None if gRC is None else float(gRC[_argmax(gRC)] - gRC[_argmax(gF)]),
                        "gap_spread_F": float(np.max(gF) - np.min(gF))})
            picks = {v: row["argmax"][v] for v in ("F", "R", "RC") if row["argmax"][v] is not None}
            if len(set(picks.values())) > 1:  # independent validation: fresh worlds, no selection on them
                v_ids = sorted(set(picks.values()), key=ids.index)
                vworlds = research.sample_worlds(nat.Env(W_VAL * len(v_ids), 0, table, single_deal=True,
                                                         encoder=net.encoder), tobs, W_VAL,
                                                 scalar_stream("validation", "c2-screen", i, k))
                venv = nat.Env(W_VAL * len(v_ids), 0, table, single_deal=True, encoder=net.encoder)
                vb = c2.evaluate(research, venv, mlp, tobs, v_ids, vworlds, predecessor=clone)
                hit = vb.event
                val = {"worlds": W_VAL, "hits": int(hit.sum()), "actions": v_ids}
                f_pick = v_ids.index(picks["F"])
                for model_name, y in (("R", vb.y["F"]), ("RC", vb.y["RC"])):
                    other = picks.get(model_name)
                    if other is None or other == picks["F"] or not hit.any():
                        continue
                    diff = y[hit][:, v_ids.index(other)] - y[hit][:, f_pick]
                    val[f"{model_name}_pick_minus_F_pick_under_{model_name}"] = {
                        "mean": float(diff.mean()), "se": float(diff.std(ddof=1) / np.sqrt(len(diff)))
                        if len(diff) > 1 else None, "n": int(len(diff))}
                row["validation"] = val
            if calibrated < n_cal_pos:
                spent_cpu = time.process_time() - c_start
                budget_left = caps["cpu_seconds"] - spent_cpu
                est = 2.5 * n_cal_worlds * k  # about 2.5 CPU-s per W128 bid search
                if est < 0.5 * budget_left:
                    seats = c2.predecessor_seats(tobs.dealer, k)
                    preds = {s: c2.SearchPredecessor(RecordingAgent(AgentSpec.of("best", s, worlds=128, seed=seed)),
                                                     research, "best:W128", tobs.dealer,
                                                     (tobs.score[0], tobs.score[1])) for s in seats}
                    agree, search_hits = 0, 0
                    for wi, w in enumerate(worlds[:n_cal_worlds]):
                        calls = []
                        for pos, s in enumerate(seats):
                            bid = preds[s].bid_for(w, s, pos)
                            calls.append(bid)
                            if (bid - 52) // 52 == 1:
                                break
                        hit = len(calls) == len(seats) and all((x - 52) // 52 == 0 for x in calls)
                        search_hits += hit
                        agree += hit == bool(b.event[wi])
                    row["calibration"] = {"worlds": n_cal_worlds, "search_hits": search_hits,
                                          "clone_hits": int(b.event[:n_cal_worlds].sum()),
                                          "event_agreement": agree / n_cal_worlds,
                                          "search_calls": sum(p.searches for p in preds.values())}
                    calibrated += 1
            positions.append(row)
    count(search_game_ids=[f"c2-screen#{d['source']}" for d in deals])
    return {"positions": positions, "deals": deals, "stopped_early": stopped,
            "total_cpu_s": time.process_time() - c_start, "total_wall_s": time.perf_counter() - t_start}


def analyse(res: dict) -> dict:
    pos = res["positions"]
    ev = [p for p in pos if p.get("evaluated")]
    out = {"source_deals": len(res["deals"]),
           "contracts": {c: sum(1 for d in res["deals"] if d["contract"] == c) for c in ("NOLO", "RAMI")},
           "reached_bids_by_k": {k: sum(1 for p in pos if p["k"] == k) for k in range(4)},
           "evaluated_positions": len(ev)}
    by_k = {}
    for p in ev:
        by_k.setdefault(p["k"], []).append(p["exclusion_rate"])
    out["exclusion_rate_clone_by_k"] = {k: {"n": len(v), "mean": float(np.mean(v)), "max": float(np.max(v))}
                                        for k, v in sorted(by_k.items())}
    out["exclusion_rate_clone_all"] = {"mean": float(np.mean([p["exclusion_rate"] for p in ev])) if ev else None,
                                       "positions_with_any_exclusion": sum(1 for p in ev if p["exclusion_rate"] > 0)}
    out["argmax_changes"] = {"R_vs_F": sum(1 for p in ev if p["argmax"]["R"] != p["argmax"]["F"]),
                             "RC_vs_F": sum(1 for p in ev if p["argmax"]["RC"] != p["argmax"]["F"]),
                             "RC_vs_R": sum(1 for p in ev if p["argmax"]["RC"] != p["argmax"]["R"])}
    for key in ("regret_of_F_under_R", "regret_of_F_under_RC", "max_abs_R_minus_F", "max_abs_RC_minus_R", "gap_spread_F"):
        v = np.array([p[key] for p in ev if p[key] is not None])
        out[key] = {"n": int(len(v)), "mean": float(v.mean()) if len(v) else None,
                    "max": float(v.max()) if len(v) else None}
    cal = [p["calibration"] for p in ev if "calibration" in p]
    out["calibration"] = {"positions": len(cal), "worlds": sum(c["worlds"] for c in cal),
                          "search_hits": sum(c["search_hits"] for c in cal), "clone_hits": sum(c["clone_hits"] for c in cal),
                          "event_agreement": float(np.mean([c["event_agreement"] for c in cal])) if cal else None,
                          "search_calls": sum(c["search_calls"] for c in cal)}
    out["live_bid_equals_F_argmax_W64"] = sum(1 for p in ev if p["live_bid_in_F_argmax"])
    for model_name in ("R", "RC"):
        key = f"{model_name}_pick_minus_F_pick_under_{model_name}"
        vals = [p["validation"][key] for p in ev if "validation" in p and key in p["validation"]]
        if vals:
            means = np.array([v["mean"] for v in vals])
            ses = np.array([v["se"] or 0.0 for v in vals])
            out[f"validated_{model_name}_vs_F"] = {
                "positions": len(vals), "mean_diff": float(means.mean()),
                "positions_significantly_better": int(np.sum(means - 1.96 * ses > 0)),
                "positions_significantly_worse": int(np.sum(means + 1.96 * ses < 0)),
                "per_commitment_gain_estimate": float(means.sum() / max(1, len(ev))),
                "note": "fresh independent validation worlds; unit = equity per reached call among evaluated positions"}
    return out


def main() -> None:
    global RESULT
    smoke = os.environ.get("C2_SCREEN_SMOKE")
    if smoke:
        RESULT = OUTPUT_DIR / "logs" / "c2_screen_smoke.json"
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
