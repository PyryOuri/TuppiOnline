"""Measure raw self-play generation throughput for partner_aware_v1."""
import time, sys
from tuppi_engine import EnginePhase, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore

spec = phase4_specifications_by_profile_key()["partner_aware_v1"]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5

t0 = time.perf_counter()
actions = deals = matches = 0
for si in range(N):
    stream = MatchStream.build(root_seed="bench-v1", stream_index=si, initial_dealer=si % 4)
    agents = tuple(construct_agent(spec, seat=s) for s in range(4))
    state = create_match(initial_score=MatchScore(0, 0), initial_dealer=stream.initial_dealer, match_ref=f"bench-{si:06d}")
    di = 0
    while not state.terminal and di < 512:
        if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
            state = begin_explicit_deal(state, stream.deal(di).explicit_deal(state.dealer))
            di += 1
            continue
        actor = state.current_actor
        obs = match_observation_for(state, actor)
        state = apply_match_action(state, agents[actor].choose_action(obs))
        actions += 1
    deals += di
    matches += 1
el = time.perf_counter() - t0
print(f"matches={matches} deals={deals} actions={actions} elapsed={el:.2f}s")
print(f"  {matches/el:.2f} matches/s  {deals/el:.1f} deals/s  {actions/el:.0f} actions/s")
print(f"  {deals/matches:.1f} deals/match  {actions/matches:.0f} actions/match  {actions/deals:.1f} actions/deal")
