"""Small, explicitly forced-NOLO qualification fixtures, not a strength bank."""
from __future__ import annotations
import ctypes as C
import json
import random
import time

from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_engine.state import EnginePhase, ACTIVE_PHASES
from tuppi_rules import Contract, MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK

from . import native
from .bridge import action_id, obs_from_player_observation
from .dan import BOT_NAME, DanAgent, DanConfig, NativeResult, diagnostic
from .lite import LiteAgent, shared_equity


def root(seed: int, plays: int = 0, match_ref: str | None = None):
    cards = list(FULL_DECK)
    random.Random(f"dan-roots-v1|{seed}").shuffle(cards)
    scores = ((0, 0), (16, 0), (0, 20), (48, 0))
    state = begin_explicit_deal(create_match(initial_score=MatchScore(*scores[seed % 4]),
        initial_dealer=seed % 4, match_ref=match_ref or f"dan-root-{seed}", ruleset_id=RulesetId.PROJECT_TARGET_V3),
        ExplicitDeal(dealer=seed % 4, hands=tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))))
    while state.phase is EnginePhase.SHOWING:
        obs = match_observation_for(state, state.current_actor)
        nolo = [a for a in obs.legal_actions if a.declared_contract is Contract.NOLO]
        if not nolo:
            return None
        state = apply_match_action(state, nolo[0])
    agents = {s: LiteAgent(s) for s in range(4)}
    for _ in range(plays):
        seat = state.current_actor
        state = apply_match_action(state, agents[seat].choose_action(match_observation_for(state, seat)))
    return state


def fixed_roots(count=16, seed_start=0):
    """First eligible roots in a finite roster; eligibility uses no rollout EV."""
    if not 1 <= count <= 16:
        raise ValueError("qualification roster has at most 16 positions")
    found = []
    schedule = (0, 1, 4, 5, 8)
    for seed in range(seed_start, seed_start+512):
        plays = schedule[len(found) % len(schedule)]
        state = root(seed, plays)
        if state is None:
            continue
        obs = match_observation_for(state, state.current_actor)
        base = action_id(LiteAgent(state.current_actor).choose_action(obs))
        ids = [action_id(a) for a in obs.legal_actions]
        if len(ids) > 1 and base % 13 < 11 and any(a % 13 >= 11 for a in ids):
            found.append((seed, plays, state))
            if len(found) == count:
                return found
    raise RuntimeError("Finite Dan qualification roster did not supply enough roots")


def probe(count=16, audit=False, seed_start=0):
    native.set_parallel(False)
    roots = fixed_roots(count, seed_start)
    rows = []
    for seed, plays, state in roots:
        obs = match_observation_for(state, state.current_actor)
        agent = DanAgent(state.current_actor)
        start, cpu = time.monotonic(), time.process_time()
        before = agent.checkpoint()
        decision = agent.propose_action(obs)
        elapsed, used = time.monotonic()-start, time.process_time()-cpu
        assert agent.checkpoint()["state"] == before["state"]
        assert agent.propose_action(obs).token == decision.token
        restored = DanAgent.from_checkpoint(json.loads(json.dumps(agent.checkpoint())))
        assert restored.propose_action(obs).token == decision.token
        applied = apply_match_action(state, decision.action)
        agent.commit_action(decision)
        committed = agent.checkpoint()
        agent.commit_action(decision)
        assert agent.checkpoint() == committed
        row = {"seed": seed, "plays": plays, "seat": state.current_actor, "cpu_seconds": used,
               "wall_seconds": elapsed, "diagnostics": decision.diagnostics,
               "checkpoint": committed, "applied_phase": applied.phase.value}
        if audit:
            ids = [action_id(a) for a in obs.legal_actions]
            env = native.Env(512*len(ids), 0, equity=shared_equity(), single_deal=True, encoder=agent._base.mlp.encoder)
            env.set_exact_speed(True)
            audit_start = time.process_time()
            matrix = native.search_world_values(env, agent._base.mlp, obs_from_player_observation(obs), ids,
                512, 0, C.c_uint64(0xA0D17000+seed))
            action_ids = __import__("numpy").ascontiguousarray(ids, dtype="int32")
            result = NativeResult()
            cfg = DanConfig()
            limit = cfg.lead_loss if plays % 4 == 0 else cfg.second_loss
            rc = native.lib.tc_dan_select(action_ids.ctypes.data, len(ids), decision.diagnostics["baseline"],
                matrix.ctypes.data, 512, limit, cfg.deal_loss, cfg.uncertainty, cfg.epsilon, C.byref(result))
            assert rc == 0
            row["audit"] = diagnostic(result, ids)
            row["audit_cpu_seconds"] = time.process_time()-audit_start
            row["same_choice_512"] = result.action == action_id(decision.action)
            native.lib.tc_env_free(env._h)
            env._h = None
        rows.append(row)
        agent.close()
        restored.close()
    return {"schema": "tuppi.dan11.probe.v1", "name": BOT_NAME, "seed_start": seed_start,
            "forced_nolo": True, "independent_strength_observations": 0,
            "config": DanConfig().__dict__, "positions": rows,
            "guard_cpu_seconds": sum(r["cpu_seconds"] for r in rows),
            "accepted": sum(r["diagnostics"]["reason"] == "accepted" for r in rows)}


def natural(count=64):
    """Short ordinary-play exposure/legality sample, never a strength result."""
    from collections import Counter
    if not 1 <= count <= 128:
        raise ValueError("natural preview is capped at 128 deals")
    native.set_parallel(False)
    dan = DanAgent(1)
    others = {s: LiteAgent(s) for s in (0, 2, 3)}
    contracts, phases, reasons = Counter(), Counter(), Counter()
    calls, traces = [], []
    for seed in range(count):
        cards = list(FULL_DECK)
        random.Random(f"dan-natural-v1|{seed}").shuffle(cards)
        state = begin_explicit_deal(create_match(initial_score=MatchScore(0, 0), initial_dealer=seed % 4,
            match_ref=f"dan-natural-{seed}", ruleset_id=RulesetId.PROJECT_TARGET_V3),
            ExplicitDeal(dealer=seed % 4, hands=tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))))
        trace = []
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            obs = match_observation_for(state, seat)
            phases[state.phase.value] += 1
            if seat == 1:
                start = time.process_time()
                decision = dan.propose_action(obs)
                action = decision.action
                reasons[decision.diagnostics["reason"]] += 1
                if decision.diagnostics["cards"]:
                    calls.append({"seed": seed, "cpu_seconds": time.process_time()-start,
                                  "diagnostics": decision.diagnostics})
            else:
                action = others[seat].choose_action(obs)
            state = apply_match_action(state, action)
            if seat == 1:
                dan.commit_action(decision)
            trace.append([seat, action_id(action)])
        contracts[state.active_deal.contract.value] += 1
        traces.append(trace)
    dan.close()
    return {"schema": "tuppi.dan11.natural_preview.v1", "name": BOT_NAME, "profile": dan.profile,
            "runtime": dan.runtime, "config": dan.config.__dict__, "deals": count, "forced_contract": False,
            "strength_evaluation": False, "dan_seat": 1, "contracts": dict(contracts),
            "phases": dict(phases), "reasons": dict(reasons), "guard_calls": calls, "traces": traces}
