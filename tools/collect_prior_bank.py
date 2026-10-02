"""Collect frozen-baseline root Q/logit records. Deferred CPU work, never runs on import.

Uses the authoritative v3 engine and the unchanged best factory. Full hands
are stored for research replay; the anchor logits use only PlayerObservation.
The bank is for decision diagnostics, not counterfactual policy strength.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT.parent / "TuppiProject-current"
SCHEMA = "tuppi.root_prior_bank.v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def commit(path):
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--deals", type=int, default=16)
    p.add_argument("--worlds", type=int, default=1024)
    p.add_argument("--seed", type=int, default=19)
    p.add_argument("--max-seconds", type=float, default=600)
    a = p.parse_args()
    if a.deals < 1 or a.worlds < 1 or not 0 < a.max_seconds < float("inf"):
        p.error("deals, worlds and max-seconds must be positive and finite")
    if a.out.exists() or a.out.with_suffix(a.out.suffix + ".partial").exists():
        p.error("output already exists; use a fresh bank path")
    lib = ROOT / "native" / "libtuppi.dylib"
    if not lib.is_file():
        p.error("isolated native library is missing; build/validate it before collection")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ENGINE / "src"))
    import torch
    import tuppi_engine
    from tuppi_engine import (ExplicitDeal, apply_match_action, begin_explicit_deal, create_match,
                              match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK, card_to_code
    from tuppi_ai import best
    from tuppi_ai.bridge import action_id, obs_from_player_observation
    from tuppi_ai import native

    if not Path(tuppi_engine.__file__).resolve().is_relative_to(ENGINE / "src"):
        raise RuntimeError("wrong authoritative engine imported")
    torch.set_num_threads(1)
    native.set_rollout_chunk(128)
    batch = best.ADAPTIVE_BIDS["batch"]
    if a.worlds > batch and a.worlds % batch:
        p.error("world count above the adaptive batch must be a batch multiple")
    agents = best.best_agents(worlds=a.worlds, seed=a.seed)
    for agent in agents.values():
        agent.record_prior = True
    manifest = {
        "kind": "manifest", "schema": SCHEMA, "ruleset": "project_target_v3", "worlds": a.worlds,
        "seed": a.seed, "requested_deals": a.deals, "max_seconds": a.max_seconds,
        "controller_state": "persistent across deals; fresh engine match and randomized score per deal",
        "tuppiai_commit": commit(ROOT), "engine_commit": commit(ENGINE), "base_spec": best.SPEC,
        "engine_source_hashes": {str(path.relative_to(ENGINE)): sha(path)
                                 for package in ("tuppi_engine", "tuppi_rules")
                                 for path in sorted((ENGINE / "src" / package).rglob("*.py"))},
        "rules_config_hashes": {str(path.relative_to(ENGINE)): sha(path)
                                for path in sorted((ENGINE / "configs" / "rules").glob("*.json"))},
        "native_sha256": sha(lib),
        "models": {name: sha(path) for name, path in (("rollout", best.ROLLOUT),
                   ("team", best.TEAM_ROLLOUT), ("anchor", best.ANCHOR), ("equity", best.EQUITY))},
        "source_hashes": {name: sha(ROOT / name) for name in
                          ("tuppi_ai/search.py", "tuppi_ai/best.py", "tuppi_ai/policy_prior.py",
                           "tuppi_ai/bridge.py", "tuppi_ai/native.py", "tuppi_ai/model.py",
                           "tuppi_ai/equity.py", "tools/collect_prior_bank.py")},
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    partial = a.out.with_suffix(a.out.suffix + ".partial")
    t0, completed, decisions = time.perf_counter(), 0, 0
    with partial.open("x") as f, trusted_transitions():
        def write(record):
            f.write(json.dumps(record, allow_nan=False) + "\n")

        write(manifest)
        for i in range(a.deals):
            if time.perf_counter() - t0 >= a.max_seconds:
                break  # soft wall cap at deal boundaries; no truncated source deals
            rng = random.Random(f"prior-bank|{a.seed}|{i}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, score = rng.randrange(4), [0, 0]
            if rng.random() >= 0.5:
                score[rng.randrange(2)] = 4 * rng.randrange(1, 13)
            match = create_match(initial_score=MatchScore(*score), initial_dealer=dealer,
                                 match_ref="prior-bank", ruleset_id=RulesetId.PROJECT_TARGET_V3)
            state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
            write({"kind": "deal", "deal": i, "dealer": dealer, "score": score,
                   "hands": [[card_to_code(c) for c in h] for h in hands]})
            step = 0
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                agent = agents[seat]
                action = agent.choose_action(obs)
                if agent.last_values is not None and agent.last_blueprint_logits is not None:
                    ids = [action_id(x) for x in obs.legal_actions]
                    write({"kind": "decision", "deal": i, "step": step, "seat": seat,
                           "phase": obs.phase.value, "action_ids": ids,
                           "values": [agent.last_values[x] for x in ids],
                           "actor_logits": [agent.last_blueprint_logits[x] for x in ids],
                           "world_counts": [agent.last_world_counts[x] for x in ids],
                           "baseline_action": action_id(action),
                           "observation_sha256": hashlib.sha256(bytes(obs_from_player_observation(obs))).hexdigest()})
                    decisions += 1
                state = apply_match_action(state, action)
                step += 1
            completed += 1
            f.flush()
        write({"kind": "completion", "completed_deals": completed, "decisions": decisions,
               "all_requested_deals": completed == a.deals, "elapsed_s": time.perf_counter() - t0})
    partial.rename(a.out)
    print(json.dumps({"bank": str(a.out), "completed_deals": completed, "decisions": decisions}))


if __name__ == "__main__":
    main()
