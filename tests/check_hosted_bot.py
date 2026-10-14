"""Bounded spawned-process qualification against frozen W1024 decisions."""
import argparse
import hashlib
import json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    from tuppi_engine import ExplicitDeal, create_match, begin_explicit_deal, match_observation_for, apply_match_action
    from tuppi_rules import MatchScore, RulesetId, FULL_DECK, card_to_index
    from tuppi_ai.bridge import action_id, engine_action
    from tuppi_ai import native
    from tuppi_server.hosted_bot import HostedSearchAgent, warm, shutdown
    reference=json.loads(args.reference.read_text());case=reference['controller_cases'][0]
    by_index={card_to_index(c):c for c in FULL_DECK}
    hands=tuple(tuple(by_index[c] for c in case['cards'][s*13:(s+1)*13]) for s in range(4))
    state=begin_explicit_deal(create_match(initial_score=MatchScore(*case['score']),initial_dealer=case['dealer'],
        match_ref='hosted-process-qualification',ruleset_id=RulesetId.PROJECT_TARGET_V3),ExplicitDeal(dealer=case['dealer'],hands=hands))
    agents={s:HostedSearchAgent(s) for s in range(4)}
    for s,a in agents.items(): a.rng_state=case['context'][s][0]+(case['context'][s][1]<<32)
    statistics=[]
    try:
        warm()
        for index,step in enumerate(case['steps'][:12]):
            seat=state.current_actor;observation=match_observation_for(state,seat)
            before=agents[seat].checkpoint()
            action=agents[seat].choose_action(observation)
            assert action_id(action)==step['action']
            assert agents[seat].rng_state==step['rng'][0]+(step['rng'][1]<<32)
            statistics.append(agents[seat].last_stats)
            if index==0:
                other=HostedSearchAgent(seat);other.restore(before)
                assert other.choose_action(observation)==action
                assert other.rng_state==agents[seat].rng_state
                restored=HostedSearchAgent(seat);restored.restore(before)
                assert restored.choose_action(observation)==action
                assert restored.checkpoint()==agents[seat].checkpoint()
            state=apply_match_action(state,engine_action(step['action'],seat))
        report={'passed':True,'worlds':1024,'decisions':len(statistics),
            'native_sha256':hashlib.sha256(Path(native.lib._name).read_bytes()).hexdigest(),
            'max_decision_seconds':max(s['decision_seconds'] for s in statistics),
            'bot_process_peak_rss_bytes':max(s['process_peak_rss_bytes'] for s in statistics),
            'checks':['frozen root actions and RNG','serial spawned bot process','per-room cursor isolation','restored cursor repeats decision'],
            'scope':'Mac portable backend, 12 synthetic positions; Linux, whole trained matches and hosted capacity remain separate'}
        args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    finally: shutdown()

if __name__=='__main__':main()
