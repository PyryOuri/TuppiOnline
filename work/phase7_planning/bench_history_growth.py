"""Is per-action cost constant or growing with match history?"""
import time
from tuppi_engine import EnginePhase, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore

spec = phase4_specifications_by_profile_key()["partner_aware_v1"]
stream = MatchStream.build(root_seed="quad-v1", stream_index=0, initial_dealer=0)
agents = tuple(construct_agent(spec, seat=s) for s in range(4))
state = create_match(initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="quad-000000")
di = 0
per_deal = []
while not state.terminal and di < 512:
    if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
        state = begin_explicit_deal(state, stream.deal(di).explicit_deal(state.dealer))
        di += 1
        t0 = time.perf_counter(); n = 0
        continue
    actor = state.current_actor
    obs = match_observation_for(state, actor)
    state = apply_match_action(state, agents[actor].choose_action(obs))
    n += 1
    if state.phase in (EnginePhase.DEAL_COMPLETE, EnginePhase.MATCH_COMPLETE):
        per_deal.append((di, n, time.perf_counter() - t0))
for d, n, t in per_deal:
    print(f"deal {d:3d}  actions {n:3d}  {t*1000/n:7.2f} ms/action")
