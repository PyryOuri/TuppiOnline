"""Upper bound on the speedup from eliding defensive revalidation.

Runs the same streams twice: once with the authoritative engine, once with
_validate_match_state / _validate_deal_state neutralised, and compares the
full action sequence for byte equality.
"""
import sys, time
import tuppi_engine.match as M
import tuppi_engine.state as S
from tuppi_engine import EnginePhase, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_engine.serialization import action_to_data
from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore

spec = phase4_specifications_by_profile_key()["partner_aware_v1"]
STREAMS = range(int(sys.argv[1]) if len(sys.argv) > 1 else 4)

def run():
    trace, actions = [], 0
    for si in STREAMS:
        stream = MatchStream.build(root_seed="fast-v1", stream_index=si, initial_dealer=si % 4)
        agents = tuple(construct_agent(spec, seat=s) for s in range(4))
        state = create_match(initial_score=MatchScore(0, 0), initial_dealer=stream.initial_dealer,
                             match_ref=f"fast-{si:06d}")
        di = 0
        while not state.terminal and di < 512:
            if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                state = begin_explicit_deal(state, stream.deal(di).explicit_deal(state.dealer))
                di += 1
                continue
            actor = state.current_actor
            obs = match_observation_for(state, actor)
            action = agents[actor].choose_action(obs)
            trace.append((si, actor, repr(action_to_data(action))))
            state = apply_match_action(state, action)
            actions += 1
        trace.append((si, "final", repr((state.score.team0, state.score.team1, di))))
    return trace, actions

t0 = time.perf_counter(); base_trace, n = run(); base = time.perf_counter() - t0
print(f"authoritative: {base:6.2f}s  {n/base:6.0f} actions/s")

orig_m, orig_s = M._validate_match_state, S._validate_deal_state
M._validate_match_state = lambda state: None
S._validate_deal_state = lambda state: None
t0 = time.perf_counter(); fast_trace, n2 = run(); fast = time.perf_counter() - t0
M._validate_match_state, S._validate_deal_state = orig_m, orig_s
print(f"validation off: {fast:6.2f}s  {n2/fast:6.0f} actions/s   speedup {base/fast:.2f}x")
print("identical play:", base_trace == fast_trace, f"({len(base_trace)} vs {len(fast_trace)} steps)")
