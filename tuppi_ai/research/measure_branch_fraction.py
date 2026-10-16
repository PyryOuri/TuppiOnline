"""Bounded measurement of C1's branch CPU fraction f (research/c1_f_measurement_manifest.json).

    python -m tuppi_ai.research.measure_branch_fraction

Plays v3 deals with the unmodified best agent at every seat (installed
library, fresh agents per deal) and times every decision with process-wide
CPU. Stops before any deal that would breach the manifest's caps.
"""

from __future__ import annotations

import json
import time

import numpy as np

from .identity import OUTPUT_DIR

MANIFEST = OUTPUT_DIR / "research" / "c1_f_measurement_manifest.json"
RESULT = OUTPUT_DIR / "logs" / "c1_branch_fraction.json"


def classify(obs) -> dict:
    phase = obs.phase.value
    n_legal = len(obs.legal_actions)
    row = {"phase": phase, "legal": n_legal, "forced": n_legal <= 1}
    if phase == "SHOWING":
        row["kind"] = "bid"
    elif phase.startswith("SOOLI"):
        row["kind"] = phase.lower()
    else:
        contract = obs.contract.value
        left = 13 - len(obs.completed_tricks)
        if not obs.current_trick:
            pos = "lead"
        elif any(a.card.suit == obs.current_trick[0].card.suit for a in obs.legal_actions):
            pos = "follow"
        else:
            pos = "discard"
        row.update({"kind": f"{contract.lower()}_{pos}", "tricks_left": left, "early": left > 6,
                    "c1_eligible": contract == "NOLO" and pos == "discard" and n_legal >= 2
                    and obs.ruleset_id.value == "project_target_v3"})
    row.setdefault("c1_eligible", False)
    return row


class Timed:
    """Times one agent's calls; pure delegation otherwise."""

    handles_sooli = True

    def __init__(self, agent, rows, deal):
        self.agent, self.rows, self.deal = agent, rows, deal

    def choose_action(self, obs):
        row = classify(obs)
        c0, t0 = time.process_time(), time.perf_counter()
        action = self.agent.choose_action(obs)
        row.update({"cpu_s": time.process_time() - c0, "wall_s": time.perf_counter() - t0, "deal": self.deal,
                    "seat": obs.observing_seat})
        self.rows.append(row)
        return action


class ForcedNolo:
    """Scripted showing (first legal NOLO card); every other decision is the wrapped agent's."""

    handles_sooli = True

    def __init__(self, agent):
        self.agent = agent

    def choose_action(self, obs):
        if obs.phase.value == "SHOWING":
            return next(a for a in obs.legal_actions if a.declared_contract.value == "NOLO")
        return self.agent.choose_action(obs)


def run() -> dict:
    from ..best import best_agents
    from .ledger import count
    from .runner_v3 import bundle_seed, new_match, play_deal
    from .streams import shuffled_deck

    m = json.loads(MANIFEST.read_text())
    caps = m["caps"]
    plan = [("natural", i) for i in range(m["populations"]["natural"]["deals"])] + \
           [("forced_nolo", i) for i in range(m["populations"]["forced_nolo"]["deals"])]
    rows, deals, stopped = [], [], None
    c_start, t_start = time.process_time(), time.perf_counter()
    for pop, i in plan:
        spent_cpu, spent_wall = time.process_time() - c_start, time.perf_counter() - t_start
        if deals:
            mean_cpu = spent_cpu / len(deals)
            mean_wall = spent_wall / len(deals)
            if (len(deals) + 1 > caps["max_deals"] or spent_cpu + mean_cpu > caps["cpu_seconds"]
                    or spent_wall + mean_wall > caps["wall_seconds"]):
                stopped = f"cap would be exceeded before {pop} #{i}"
                break
        ns = m["populations"][pop]["deck_namespace"]
        hands = shuffled_deck("deal", ns, i)
        agents = best_agents(worlds=128, seed=bundle_seed(ns, i), team_rollout=False)  # B0: the audited configuration (clone rollouts on every seat)
        deal_id = f"{pop}#{i}"
        wrapped = {s: Timed(ForcedNolo(a) if pop == "forced_nolo" else a, rows, deal_id) for s, a in agents.items()}
        c0, t0 = time.process_time(), time.perf_counter()
        out = play_deal(new_match((0, 0), i % 4, match_ref="research-c1f"), wrapped, hands)
        r = out.state.completed_deals[-1].public_result if not out.failed else None
        deals.append({"deal": deal_id, "population": pop, "dealer": i % 4, "failed": out.failed,
                      "failure": out.failure, "contract": None if r is None else r.contract.value,
                      "soolaaja": None if r is None else getattr(r, "soolaaja", None),
                      "cpu_s": time.process_time() - c0, "wall_s": time.perf_counter() - t0})
    count(search_game_ids=[d["deal"] + "@c1-f-measurement" for d in deals])
    return {"rows": rows, "deals": deals, "stopped_early": stopped,
            "total_cpu_s": time.process_time() - c_start, "total_wall_s": time.perf_counter() - t_start}


def analyse(res: dict, reps: int = 4000) -> dict:
    rows, deals = res["rows"], res["deals"]
    nat = [d["deal"] for d in deals if d["population"] == "natural" and not d["failed"]]
    forced = [d["deal"] for d in deals if d["population"] == "forced_nolo" and not d["failed"]]

    def per_deal(ids, pred):
        return np.array([sum(r["cpu_s"] for r in rows if r["deal"] == d and pred(r)) for d in ids])

    def by_kind(ids):
        out = {}
        for r in rows:
            if r["deal"] in ids:
                k = r["kind"] + ("" if r["phase"] in ("SHOWING",) or r["phase"].startswith("SOOLI")
                                 else ("_early" if r.get("early") else "_late"))
                e = out.setdefault(k, {"decisions": 0, "searched": 0, "cpu_s": 0.0})
                e["decisions"] += 1
                e["searched"] += not r["forced"]
                e["cpu_s"] += r["cpu_s"]
        total = sum(e["cpu_s"] for e in out.values()) or 1.0
        for e in out.values():
            e["cpu_share"] = e["cpu_s"] / total
            e["cpu_s_per_searched"] = e["cpu_s"] / e["searched"] if e["searched"] else None
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["cpu_s"]))

    total_nat = per_deal(nat, lambda r: True)
    elig_nat = per_deal(nat, lambda r: r["c1_eligible"])
    rng = np.random.default_rng(0)
    f_nat = float(elig_nat.sum() / total_nat.sum()) if len(nat) else None
    boots = []
    for _ in range(reps):
        idx = rng.integers(0, len(nat), len(nat))
        boots.append(elig_nat[idx].sum() / total_nat[idx].sum())
    nolo_nat = sum(1 for d in deals if d["population"] == "natural" and d["contract"] == "NOLO")
    elig_forced = per_deal(forced, lambda r: r["c1_eligible"])
    c_nolo = float(elig_forced.mean()) if len(forced) else None
    cpu_per_nat_deal = float(total_nat.mean()) if len(nat) else None
    model = {}
    if c_nolo is not None and cpu_per_nat_deal:
        for p in (0.05, 0.10, 0.15, 0.20, 0.30):
            model[str(p)] = p * c_nolo / cpu_per_nat_deal
    f_hi = max([f_nat or 0.0] + [float(np.quantile(boots, 0.975))] + list(model.values()))
    return {
        "natural_deals": len(nat), "natural_nolo_deals": nolo_nat,
        "natural_contracts": [d["contract"] for d in deals if d["population"] == "natural"],
        "cpu_per_natural_deal_s": cpu_per_nat_deal,
        "f_natural": f_nat, "f_natural_bootstrap95": [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))],
        "c1_eligible_cpu_per_forced_nolo_deal_s": c_nolo,
        "c1_eligible_decisions_per_forced_nolo_deal": (sum(1 for r in rows if r["deal"] in forced and r["c1_eligible"])
                                                       / len(forced)) if forced else None,
        "f_model_by_nolo_share": model,
        "total_saving_bound_f_times_r": {str(r): r * f_hi for r in (0.1, 0.35, 0.5)},
        "f_used_for_bound": f_hi,
        "cpu_by_decision_kind_natural": by_kind(set(nat)),
        "cpu_by_decision_kind_forced_nolo": by_kind(set(forced)),
    }


def main() -> None:
    res = run()
    summary = analyse(res)
    out = {"manifest": str(MANIFEST), "run": {k: v for k, v in res.items() if k != "rows"}, "summary": summary,
           "rows": res["rows"]}
    RESULT.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({"run": out["run"], "summary": {k: v for k, v in summary.items()
                                                      if not k.startswith("cpu_by")}}, indent=1, default=str))


if __name__ == "__main__":
    main()
