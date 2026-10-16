"""P.C5 stage 1 screen (research/c5_screen_manifest.json): coverage, cost, model comparison, transfer.

    python -m tuppi_ai.research.c5_screen

Natural v3 deals by the unmodified best agents; at each deal's three-card
lead boundary the position is measured under the fixed-clone model and then
the real deal is finished twice from the same state - root = W128 fork vs
root = C5Agent (fallback: the root's own W128 fork) - with forked W128 agents
at the other seats. Runs on R0-parity (needed for NativeFork).
"""

from __future__ import annotations

import json
import time

import numpy as np

from .identity import OUTPUT_DIR

MANIFEST = OUTPUT_DIR / "research" / "c5_screen_manifest.json"
RESULT = OUTPUT_DIR / "logs" / "c5_screen_stage1.json"


def _finish(state, agents):
    from tuppi_engine import apply_match_action, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES

    actions = []
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        obs = match_observation_for(state, seat)
        t0 = time.perf_counter()
        action = agents[seat].choose_action(obs)
        actions.append((seat, obs.phase.value, 1000 * (time.perf_counter() - t0)))
        state = apply_match_action(state, action)
    return state, actions


def _root_utility(state, root, equity) -> float:
    r = state.completed_deals[-1].public_result
    d0 = equity.delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), r.dealer)
    return d0 if root % 2 == 0 else -d0


def run() -> dict:
    from .native_api import RESEARCH_LIB, ResearchLibrary, bind_native

    nat = bind_native(RESEARCH_LIB)
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES

    from ..best import EQUITY
    from ..bridge import action_id, obs_from_player_observation
    from ..equity import Equity
    from . import c5_option as O
    from .clone_policy import rollout_network
    from .ledger import count
    from .lifecycle import AgentSpec, RecordingAgent, native_fork
    from .runner_v3 import bundle_seed, new_match
    from .streams import shuffled_deck

    import os

    m = json.loads(MANIFEST.read_text())
    caps, ns = dict(m["caps"]), m["population"]["deck_namespace"]
    if os.environ.get("C5_SCREEN_SMOKE"):  # a tiny pre-flight inside the same caps, results kept apart
        caps["max_source_deals"] = int(os.environ["C5_SCREEN_SMOKE"])
    research = ResearchLibrary()
    equity = Equity.load(EQUITY)
    net = rollout_network()
    mlp = nat.Mlp(net)
    rows, stopped = [], None
    c_start, t_start = time.process_time(), time.perf_counter()
    for i in range(caps["max_source_deals"]):
        positions = sum(1 for r in rows if r.get("eligible"))
        if positions >= caps["target_positions"]:
            break
        spent_cpu, spent_wall = time.process_time() - c_start, time.perf_counter() - t_start
        if rows and (spent_cpu + spent_cpu / len(rows) > caps["cpu_seconds"]
                     or spent_wall + spent_wall / len(rows) > caps["wall_seconds"]):
            stopped = f"cap would be exceeded before source deal {i}"
            break
        dealer = i % 4
        hands = shuffled_deck("deal", ns, i)
        seed = bundle_seed(ns, i)
        live = {s: RecordingAgent(AgentSpec.of("best", s, worlds=128, seed=seed)) for s in range(4)}
        state = begin_explicit_deal(new_match((0, 0), dealer, "research-c5"), ExplicitDeal(dealer=dealer, hands=hands))
        c0 = time.process_time()
        reached = None
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            obs = match_observation_for(state, seat)
            if O.eligible(obs):
                reached = obs
                break
            state = apply_match_action(state, live[seat].choose_action(obs))
        row = {"source": i, "dealer": dealer, "prefix_cpu_s": time.process_time() - c0}
        if reached is None:
            r = state.completed_deals[-1].public_result
            row.update({"eligible": False, "gate": "no ordinary three-card lead boundary",
                        "contract": r.contract.value, "sooli": getattr(r, "soolaaja", None) is not None})
            rows.append(row)
            continue
        root = reached.observing_seat
        tobs = obs_from_player_observation(reached)
        ids = [action_id(a) for a in reached.legal_actions]
        row.update({"eligible": True, "root": root, "contract": reached.contract.value,
                    "declarer_team": None if reached.declarer is None else reached.declarer % 2})
        t0 = time.perf_counter()
        sup = O.complete_support(reached)
        row.update({"support_status": sup.status, "support": sup.native_count,
                    "support_ms": 1000 * (time.perf_counter() - t0)})
        # ---- fixed-clone model comparison
        if sup.status == "EXACT_COMPLETE":
            model = O.NativeModel(mlp, net.encoder, equity)
            res = O.solve_option(tobs, sup.worlds, model, ids)
            fork_m = native_fork(live[root], research)
            w_lead = action_id(fork_m.choose_action(reached))
            cache = {}

            def later(o, fork_m=fork_m, cache=cache):
                key = O.root_key(o)
                if key not in cache:
                    f = native_fork(fork_m, research)
                    legal = nat.legal_obs(o)
                    cand = [c for c in ids if c in legal] + [c for c in legal if c not in ids]
                    vals = f.agent.searcher.action_values(o, cand)
                    cache[key] = cand[max(range(len(cand)), key=lambda j: (vals[j], -j))]
                return cache[key]

            v_w128 = O.policy_value(tobs, sup.worlds, O.NativeModel(mlp, net.encoder, equity), w_lead, later)
            clair = O.root_clairvoyant_value(tobs, sup.worlds, O.NativeModel(mlp, net.encoder, equity), ids)
            row.update({"model": {"q": {str(k): v for k, v in res.q.items()}, "option_lead": res.chosen,
                                  "w128_lead": w_lead, "q_option": res.q[res.chosen],
                                  "q_w128_lead_plus_option": res.q[w_lead], "v_w128_policy": v_w128,
                                  "clairvoyant": clair, "nodes": res.nodes, "solve_ms": 1000 * res.wall_s,
                                  "w128_later_calls": len(cache)}})
        # ---- transfer: finish the real deal twice from the same state
        agents_w = {s: native_fork(live[s], research) for s in range(4)}
        end_w, acts_w = _finish(state, agents_w)
        agents_c = {s: native_fork(live[s], research) for s in range(4) if s != root}
        c5 = O.C5Agent(native_fork(live[root], research), mlp, net.encoder, equity, deadline_s=0.1)
        agents_c[root] = c5
        end_c, acts_c = _finish(state, agents_c)
        u_w, u_c = _root_utility(end_w, root, equity), _root_utility(end_c, root, equity)
        root_ms = [ms for s, _p, ms in acts_c if s == root]
        row.update({"transfer": {"u_w128": u_w, "u_c5": u_c, "diff": u_c - u_w, "c5_log": c5.log,
                                 "c5_first_decision_ms": root_ms[0] if root_ms else None,
                                 "root_tricks_w128": end_w.completed_deals[-1].public_result.team_tricks[root % 2],
                                 "root_tricks_c5": end_c.completed_deals[-1].public_result.team_tricks[root % 2]}})
        rows.append(row)
    count(search_game_ids=[f"c5-screen#{r['source']}" for r in rows])
    return {"rows": rows, "stopped_early": stopped, "total_cpu_s": time.process_time() - c_start,
            "total_wall_s": time.perf_counter() - t_start}


def analyse(res: dict) -> dict:
    rows = res["rows"]
    elig = [r for r in rows if r.get("eligible")]
    exact = [r for r in elig if r["support_status"] == "EXACT_COMPLETE"]
    diffs = np.array([r["transfer"]["diff"] for r in elig])
    started = [r for r in elig if any(e["event"] == "option_started" for e in r["transfer"]["c5_log"])]
    followed = [r for r in started if any(e["event"] == "option_followed" for e in r["transfer"]["c5_log"])]
    offkey = [r for r in started if any(e.get("reason", "").startswith("unexpected") for e in r["transfer"]["c5_log"])]
    lead_diff = [r for r in exact if r["model"]["option_lead"] != r["model"]["w128_lead"]]
    model_gain = np.array([r["model"]["q_option"] - r["model"]["v_w128_policy"] for r in exact])
    lat = np.array([r["transfer"]["c5_first_decision_ms"] for r in elig if r["transfer"]["c5_first_decision_ms"]])

    def ci(x):
        if len(x) < 2:
            return {"n": int(len(x)), "mean": float(x.mean()) if len(x) else None}
        m, se = float(x.mean()), float(x.std(ddof=1) / np.sqrt(len(x)))
        return {"n": int(len(x)), "mean": m, "sd": float(x.std(ddof=1)), "ci95": [m - 1.96 * se, m + 1.96 * se]}

    statuses = {}
    for r in elig:
        statuses[r["support_status"]] = statuses.get(r["support_status"], 0) + 1
    return {
        "source_deals": len(rows), "eligible_positions": len(elig),
        "gate_failures": {g: sum(1 for r in rows if not r.get("eligible") and r["gate"] == g)
                          for g in {r["gate"] for r in rows if not r.get("eligible")}},
        "ineligible_contracts": [(r["contract"], r["sooli"]) for r in rows if not r.get("eligible")],
        "support_status": statuses, "coverage_exact": len(exact) / len(elig) if elig else None,
        "support_sizes": sorted(r["support"] for r in exact),
        "options_started_in_transfer": len(started), "options_followed_later": len(followed),
        "off_support_fallbacks_in_transfer": len(offkey),
        "lead_disagreement_model": len(lead_diff),
        "model_gain_option_minus_w128_policy": ci(model_gain),
        "model_gain_nonzero_positions": int((np.abs(model_gain) > 1e-12).sum()),
        "transfer_diff_c5_minus_w128": ci(diffs),
        "transfer_nonzero_positions": int((np.abs(diffs) > 1e-12).sum()),
        "transfer_positive": int((diffs > 1e-12).sum()), "transfer_negative": int((diffs < -1e-12).sum()),
        "c5_first_decision_latency_ms": {"n": int(len(lat)), "p50": float(np.quantile(lat, 0.5)) if len(lat) else None,
                                         "p95": float(np.quantile(lat, 0.95)) if len(lat) else None,
                                         "max": float(lat.max()) if len(lat) else None},
        "nodes_max": max((r["model"]["nodes"] for r in exact), default=None),
    }


def main() -> None:
    import os

    global RESULT
    if os.environ.get("C5_SCREEN_SMOKE"):
        RESULT = OUTPUT_DIR / "logs" / "c5_screen_smoke.json"
    res = run()
    summary = analyse(res)
    RESULT.write_text(json.dumps({"manifest": str(MANIFEST), "run": {k: v for k, v in res.items() if k != "rows"},
                                  "summary": summary, "rows": res["rows"]}, indent=1, default=str))
    print(json.dumps({"run": {k: v for k, v in res.items() if k != "rows"}, "summary": summary}, indent=1, default=str))


if __name__ == "__main__":
    main()
