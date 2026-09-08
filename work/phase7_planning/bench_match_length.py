"""Match-length distribution and fast-path throughput over many streams."""
import statistics, sys, time
import tuppi_engine.match as M, tuppi_engine.state as S
M._validate_match_state = lambda state: None
S._validate_deal_state = lambda state: None
from tuppi_engine import EnginePhase, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore

spec = phase4_specifications_by_profile_key()["partner_aware_v1"]
N = int(sys.argv[1])
lens, acts = [], []
t0 = time.perf_counter()
total_actions = 0
for si in range(N):
    stream = MatchStream.build(root_seed="dist-v1", stream_index=si, initial_dealer=si % 4)
    agents = tuple(construct_agent(spec, seat=s) for s in range(4))
    state = create_match(initial_score=MatchScore(0, 0), initial_dealer=stream.initial_dealer, match_ref=f"dist-{si:06d}")
    di = a = 0
    while not state.terminal and di < 512:
        if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
            state = begin_explicit_deal(state, stream.deal(di).explicit_deal(state.dealer)); di += 1; continue
        actor = state.current_actor
        obs = match_observation_for(state, actor)
        state = apply_match_action(state, agents[actor].choose_action(obs))
        a += 1
    lens.append(di); acts.append(a); total_actions += a
el = time.perf_counter() - t0
lens.sort()
q = lambda p: lens[min(len(lens)-1, int(p*len(lens)))]
print(f"{N} matches in {el:.1f}s -> {total_actions/el:.0f} actions/s, {N/el:.2f} matches/s")
print(f"deals/match: mean {statistics.mean(lens):.1f} median {q(0.5)} p90 {q(0.9)} p99 {q(0.99)} max {lens[-1]}")
print(f"actions/match: mean {statistics.mean(acts):.0f}; actions/deal {total_actions/sum(lens):.1f}")
print(f"hit 512 cap: {sum(1 for l in lens if l>=512)}")
