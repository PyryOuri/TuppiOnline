#!/usr/bin/env python3
"""One bounded, fresh-process job. Called by launch.py, never a live server."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import random
import resource
import signal
import statistics
import sys
import time

from bootstrap import activate
from statistics_tools import interval, match_pair, matches


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def controller_seed(seed, parent, rotation, team):
    # Same controllers wherever two arms still have the same information.
    # Both team assignments/paired legs start with the same indexed seat
    # streams in separately owned controllers; the pair is the inference unit.
    return int(stable_hash([seed, "controller", parent, rotation])[:8], 16)


def score_for(seed, index, design):
    if design == "zero":
        return (0, 0)
    cell = random.Random(f"{seed}|score|{index}").randrange(25)
    return (4 * cell, 0) if cell <= 12 else (0, 4 * (cell - 12))


def cards_for(seed, index):
    from tuppi_rules.cards import FULL_DECK
    cards = list(FULL_DECK)
    random.Random(f"{seed}|deal|{index}").shuffle(cards)
    return cards


def make_agents(name, worlds, seed, seats):
    from candidates import ARMS, agents, loaded
    if name in ARMS:
        return agents(name, worlds=worlds, seed=seed, seats=seats)
    if name == "vrpo3":
        from tuppi_ai import best
        from tuppi_ai.policies import Greedy, PolicyAgent
        from tuppi_agents.sooli import SooliFallbackAgent
        return {s: SooliFallbackAgent(PolicyAgent(Greedy(loaded(str(best.ANCHOR))), s)) for s in seats}
    if name == "heuristic_v3":
        from tuppi_ai.incumbent import incumbent_agents
        from tuppi_agents.sooli import SooliFallbackAgent
        all_agents = incumbent_agents("partner_aware_lead_v3")
        return {s: SooliFallbackAgent(all_agents[s]) for s in seats}
    raise ValueError("Unknown opponent")


def play(state, actors, decision_rows=None):
    from tuppi_engine import action_to_data, apply_match_action, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_ai.bridge import action_id
    trace = hashlib.sha256()
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        actor = actors[seat]
        observation = match_observation_for(state, seat)
        before = time.perf_counter()
        action = actor.choose_action(observation)
        elapsed = time.perf_counter() - before
        if action not in observation.legal_actions:
            raise RuntimeError("Candidate proposed an illegal authoritative action")
        values = getattr(actor, "last_values", None)
        entry = {"seat": seat, "phase": observation.phase.value, "action": action_to_data(action),
                 "values": None if values is None else {str(a): float(v).hex() for a, v in values.items()},
                 "rng": getattr(getattr(getattr(actor, "searcher", None), "rng", None), "value", None)}
        trace.update(json.dumps(entry, sort_keys=True).encode())
        if decision_rows is not None:
            decision_rows.append({"seat": seat, "phase": observation.phase.value, "action": action_id(action),
                                  "seconds": elapsed, "world_counts": getattr(actor, "last_world_counts", None)})
        state = apply_match_action(state, action)
    return state, trace.hexdigest()


def duplicate(job, context):
    from candidates import equity
    from tuppi_engine import ExplicitDeal, begin_explicit_deal, create_match
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    rows = []
    for index in range(job["samples"]):
        cards = cards_for(job["seed"], index)
        base = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
        score = score_for(job["seed"], index, job["scores"])
        games = []
        with trusted_transitions():
            for rotation in range(4):
                hands = tuple(base[(s + rotation) % 4] for s in range(4))
                for team in (0, 1):
                    seed = controller_seed(job["seed"], index, rotation, team)
                    # Fresh env/RNG/sooli state for each indexed game; models are
                    # immutable cached weights. Preserve hand and legal order.
                    own = make_agents(job["arm"], job["worlds"], seed, [s for s in range(4) if s % 2 == team])
                    other = make_agents(job["opponent"], job["worlds"], seed, [s for s in range(4) if s % 2 != team])
                    state = begin_explicit_deal(create_match(initial_score=MatchScore(*score), initial_dealer=0,
                            match_ref=f"cw-{index}-{rotation}-{team}", ruleset_id=RulesetId.PROJECT_TARGET_V3),
                            ExplicitDeal(dealer=0, hands=hands))
                    state, fp = play(state, {**own, **other})
                    result = state.completed_deals[-1].public_result
                    delta = equity().delta0(result.score_before.as_tuple(), result.score_after.as_tuple(), 0)
                    games.append({"rotation": rotation, "team": team, "value": delta if team == 0 else -delta,
                                  "won": result.deal_score.winner_team.value == team, "fingerprint": fp})
        identity = stable_hash({"cards": [str(c) for c in cards], "index": index, "score": score, "dealer": 0})
        row = {"index": index, "deal_id": identity, "score": list(score), "value": statistics.fmean(g["value"] for g in games), "games": games}
        rows.append(row)
        print(json.dumps({"completed_parent": index, "parents_required": job["samples"]}), flush=True)
    return {"schema": "tuppi.cheap_wins.duplicate.v1", "candidate": job["arm"], "opponent": job["opponent"],
            "ruleset": "project_target_v3", "seed": job["seed"], "scores": job["scores"],
            "base_deals": len(rows), "values": [r["value"] for r in rows], "deal_records": rows,
            "summary": interval([r["value"] for r in rows]), "context": context}


def full_deals(job, context):
    from tuppi_engine import ExplicitDeal, begin_explicit_deal, create_match
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    rows, actors = [], None
    with trusted_transitions():
        for index in range(job["samples"]):
            # Retained controllers across deals exercise the as-is v3 setting
            # persistence. This is distinct from indexed duplicate bundles.
            if actors is None:
                actors = make_agents(job["arm"], job["worlds"], controller_seed(job["seed"], 0, 0, 0), range(4))
            cards = cards_for(job["seed"], index)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, score = index % 4, score_for(job["seed"], index, job["scores"])
            state = begin_explicit_deal(create_match(initial_score=MatchScore(*score), initial_dealer=dealer,
                        match_ref=f"cw-profile-{index}", ruleset_id=RulesetId.PROJECT_TARGET_V3),
                        ExplicitDeal(dealer=dealer, hands=hands))
            decisions = []
            state, fingerprint = play(state, actors, decisions)
            rows.append({"index": index, "fingerprint": fingerprint, "decisions": decisions})
            print(json.dumps({"completed_deal": index}), flush=True)
    return {"schema": "tuppi.cheap_wins.full_deals.v1", "candidate": job["arm"], "rows": rows, "context": context}


def match_cost(job, context):
    from tuppi_engine import ExplicitDeal, begin_explicit_deal, create_match
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId, Team
    pairs = []
    with trusted_transitions():
        for pair in range(job["samples"]):
            legs = []
            for team in (0, 1):
                seed = controller_seed(job["seed"], pair, 0, team)
                own = make_agents(job["arm"], job["worlds"], seed, [s for s in range(4) if s % 2 == team])
                other = make_agents(job["opponent"], job["worlds"], seed, [s for s in range(4) if s % 2 != team])
                state = create_match(initial_score=MatchScore(0, 0), initial_dealer=0,
                            match_ref=f"cw-match-{pair}-{team}", ruleset_id=RulesetId.PROJECT_TARGET_V3)
                count = 0
                while not state.terminal and count < job["match_cap"]:
                    cards = cards_for(f"{job['seed']}|pair|{pair}", count)
                    hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
                    state = begin_explicit_deal(state, ExplicitDeal(dealer=state.dealer, hands=hands))
                    state, _ = play(state, {**own, **other})
                    count += 1
                legs.append({"result": float(state.score.for_team(Team(team)) >= 52) if state.terminal else None,
                             "censored": not state.terminal, "deals": count})
            pairs.append(match_pair(*legs))
    return {"schema": "tuppi.cheap_wins.match_cost.v1", "candidate": job["arm"], "opponent": job["opponent"],
            "pairs": pairs, "summary": matches(pairs), "context": context}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    envelope = json.loads(args.job.read_text())
    job, context = envelope["job"], envelope["context"]
    resource.setrlimit(resource.RLIMIT_CPU, (job["cpu_seconds"], job["cpu_seconds"]))
    signal.alarm(job["wall_seconds"])
    t0, c0 = time.perf_counter(), time.process_time()
    activate()
    import torch
    torch.set_num_threads(1)
    from candidates import configure_native
    configure_native(job["arm"], serial=job["serial"])
    result = {"duplicate": duplicate, "full_deals": full_deals, "match_cost": match_cost}[job["kind"]](job, context)
    result.update({"seconds": time.perf_counter() - t0, "cpu_seconds": time.process_time() - c0,
                   "job": job, "peak_rss_bytes_macos": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   "dependency_versions": {"torch": torch.__version__, "numpy": __import__("numpy").__version__,
                                           "python": sys.version, "executable": sys.executable}})
    with args.out.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    signal.alarm(0)


if __name__ == "__main__":
    main()
