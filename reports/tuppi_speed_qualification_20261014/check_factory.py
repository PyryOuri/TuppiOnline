"""Check common speed settings keep each prepared strength arm correctly wired."""
import json
import resource
import signal
from bindings import OUT,activate,agents


def main():
    resource.setrlimit(resource.RLIMIT_CPU,(30,30)); signal.alarm(45)
    candidates,native,best=activate('compact128',parallel=False)
    from tuppi_engine import ExplicitDeal,begin_explicit_deal,create_match,match_observation_for
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore,RulesetId
    from tuppi_rules.cards import card_from_index
    from tuppi_ai.bridge import action_id
    case=json.loads((OUT/'FIXTURES.json').read_text())['rule_cases'][0]
    hands=tuple(tuple(card_from_index(c) for c in case['cards'][s*13:(s+1)*13]) for s in range(4))
    rows=[]
    with trusted_transitions():
        state=begin_explicit_deal(create_match(initial_score=MatchScore(*case['score']),initial_dealer=case['dealer'],
            match_ref='speed-factory-check',ruleset_id=RulesetId.PROJECT_TARGET_V3),ExplicitDeal(dealer=case['dealer'],hands=hands))
        obs=match_observation_for(state,state.current_actor)
        for arm in ('baseline','hard_anchor','suit_ensemble'):
            team=agents(candidates,native,best,'compact128',256,seed=35,arm=arm)
            assert team[0].searcher.mlp is team[2].searcher.mlp
            assert team[0].searcher.env is not team[2].searcher.env and team[0].searcher.rng is not team[2].searcher.rng
            actor=team[state.current_actor]
            assert actor.arm==arm and actor.keep==0.003 and actor.keep_show==0.03
            assert getattr(actor.searcher.env,'_team_mlp',None) is None
            assert (actor.anchor_mlp is not None)==(arm=='suit_ensemble')
            action=actor.choose_action(obs)
            assert action in obs.legal_actions and actor.last_values and actor.last_world_counts
            if arm=='hard_anchor': assert actor.last_anchor in actor.last_values
            rows.append({'arm':arm,'action':action_id(action),'keep':actor.keep,'keep_show':actor.keep_show,
                         'searched_actions':len(actor.last_values),'world_counts':actor.last_world_counts})
    with (OUT/'FACTORY_CHECK.json').open('x') as f: json.dump({'status':'PASS','scope':'One legal W256 bid per prepared arm; factory wiring, not strength','rows':rows},f,indent=2)
    print('Common speed factory: all three prepared arms passed.')
    signal.alarm(0)


if __name__=='__main__': main()
