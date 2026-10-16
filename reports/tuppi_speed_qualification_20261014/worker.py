"""One finite qualification job through the frozen authoritative v3 engine."""
import argparse
import collections
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import resource
import signal
import sys
import time

from bindings import OUT,PREP,activate,agents,track_sooli


def sha(value): return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True); parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); job=json.loads(args.job.read_text())
    resource.setrlimit(resource.RLIMIT_CPU,(job['cpu_seconds'],job['cpu_seconds']))
    signal.alarm(job['wall_seconds'])
    started,initial_cpu=time.perf_counter(),time.process_time()
    candidates,native,best=activate(job['variant'],parallel=job['parallel'])
    import numpy as np
    import torch
    from tuppi_engine import ExplicitDeal,begin_explicit_deal,create_match,match_observation_for,apply_match_action
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore,RulesetId
    from tuppi_rules.cards import card_from_index
    from tuppi_ai.bridge import action_id,engine_action,obs_from_player_observation
    fixtures=json.loads((OUT/'FIXTURES.json').read_text())['rule_cases']
    construction={'seconds':0.,'cpu_seconds':0.,'factories':0}

    def make(worlds,seed):
        a,c=time.perf_counter(),time.process_time()
        team=agents(candidates,native,best,job['variant'],worlds,seed)
        for actor in team.values(): track_sooli(actor)
        construction['seconds']+=time.perf_counter()-a; construction['cpu_seconds']+=time.process_time()-c; construction['factories']+=1
        return team

    def begin(cards,dealer,score,label):
        hands=tuple(tuple(card_from_index(c) for c in cards[s*13:(s+1)*13]) for s in range(4))
        return begin_explicit_deal(create_match(initial_score=MatchScore(*score),initial_dealer=dealer,match_ref=label,
            ruleset_id=RulesetId.PROJECT_TARGET_V3),ExplicitDeal(dealer=dealer,hands=hands))

    def decision(state,actors,label):
        seat=state.current_actor; actor=actors[seat]
        obs=match_observation_for(state,seat); native_obs=obs_from_player_observation(obs)
        before=list(actor.searcher.env.qualification_sooli)
        a,c=time.perf_counter(),time.process_time(); action=actor.choose_action(obs)
        wall,cpu=time.perf_counter()-a,time.process_time()-c
        if action not in obs.legal_actions: raise RuntimeError('Illegal authoritative action')
        values=actor.last_values
        exact={'label':label,'seat':seat,'phase':obs.phase.value,'contract':None if obs.contract is None else obs.contract.value,
            'input_sha256':hashlib.sha256(bytes(native_obs)).hexdigest(),'legal':[action_id(x) for x in obs.legal_actions],
            'action':action_id(action),'values':None if values is None else {str(k):float(v).hex() for k,v in values.items()},
            'rng':actor.searcher.rng.value,'world_counts':actor.last_world_counts,
            'sooli_before':before,'sooli_after':list(actor.searcher.env.qualification_sooli)}
        return action,{'exact':exact,'seconds':wall,'cpu_seconds':cpu}

    rows=[]
    with trusted_transitions():
        if job['mode']=='native_roots':
            from native_roots import roots
            specs=list(roots(native))
            for index in range(64):
                rng=random.Random(f'speed-extra-root|{index}'); deck=list(range(52)); rng.shuffle(deck)
                hands=[sum(1<<c for c in deck[s*13:(s+1)*13]) for s in range(4)]
                cell=index%25; score=(4*cell,0) if cell<=12 else (0,4*(cell-12))
                d=native.new_deal(hands,index%4,*score,ruleset=3)
                contract=index%2
                while d.phase!=native.PH_PLAY:
                    legal=native.legal(d)
                    matches=[x for x in legal if (x-52)//52==contract] if d.phase==native.PH_SHOW else []
                    action=(matches or legal)[0] if d.phase==native.PH_SHOW else native.ACT_SOOLI_DECLINE
                    assert native.lib.tc_apply(C.byref(d),action)==0
                target=28+index%23
                while d.n_played<target:
                    assert native.lib.tc_apply(C.byref(d),rng.choice(native.legal(d)))==0
                ob=native.observe(d,d.cur); ids=native.legal(d)
                specs.append((index+14,ob,ids,16,index%3))
            for index,obs,ids,worlds,setting in specs:
                actor=make(worlds,index+19)[obs.seat]; sr=actor.searcher
                if setting: sr.env.set_sooli(17,False,setting==1,0.3)
                a,c=time.perf_counter(),time.process_time(); values=sr.action_values(obs,ids)
                exact={'index':index,'input_sha256':hashlib.sha256(bytes(obs)).hexdigest(),'ids':ids,'worlds':worlds,
                    'contract':int(obs.contract),'played':int(obs.n_played),
                    'values':[float(v).hex() for v in values],'rng':sr.rng.value,'sooli_options':list(sr.env.qualification_sooli)}
                rows.append({'exact':exact,'seconds':time.perf_counter()-a,'cpu_seconds':time.process_time()-c})
        elif job['mode'] in ('history_bank','forced_sooli'):
            actors=make(job['worlds'],276513)
            cases=fixtures if job['mode']=='history_bank' else fixtures[:1]
            for case in cases:
                state=begin(case['cards'],case['dealer'],case['score'],case['id'])
                phase_seen=collections.Counter(); seen_targets=set()
                for step,scripted in enumerate(case['prefix']):
                    obs=match_observation_for(state,state.current_actor); phase=obs.phase.value
                    count=phase_seen[phase]; phase_seen[phase]+=1
                    played=obs_from_player_observation(obs).n_played
                    if job['mode']=='forced_sooli':
                        query=phase in {'SOOLI_OFFER','SOOLI_GIVE','SOOLI_RETURN'} and count==0 or phase=='SOOLI_PLAY' and count<3
                    else:
                        query=phase in {'SHOWING','SOOLI_OFFER','SOOLI_GIVE','SOOLI_RETURN'} and count==0 or phase=='SOOLI_PLAY' and count<3
                        if phase=='TRICK_PLAY' and played in (0,1,28,29,40,41) and played not in seen_targets:
                            query=True; seen_targets.add(played)
                    if query:
                        _,row=decision(state,actors,f'{case["id"]}:{step}'); rows.append(row)
                    action=engine_action(scripted,state.current_actor)
                    assert action in obs.legal_actions, (case['id'],step,scripted)
                    state=apply_match_action(state,action)
                assert state.phase not in ACTIVE_PHASES
        elif job['mode']=='games':
            # Reproduce its deterministic fixed-deal inputs directly, retaining
            # controllers across the two deals and preserving every hand order.
            seed=job['seed']
            actor_seed=int(sha([seed,'controller',0,0])[:8],16)
            actors=make(job['worlds'],actor_seed)
            from tuppi_rules.cards import FULL_DECK,card_to_index
            for index in range(job['samples']):
                cards=list(FULL_DECK); random.Random(f'{seed}|deal|{index}').shuffle(cards)
                cell=random.Random(f'{seed}|score|{index}').randrange(25)
                score=(4*cell,0) if cell<=12 else (0,4*(cell-12))
                state=begin([card_to_index(c) for c in cards],index%4,score,f'qualification-{index}')
                step=0
                while state.phase in ACTIVE_PHASES:
                    action,row=decision(state,actors,f'game{index}:{step}'); rows.append(row)
                    state=apply_match_action(state,action); step+=1
        else: raise ValueError('Unknown mode')
    exact=[row['exact'] for row in rows]
    result={'schema':'tuppi.speed_qualification.result.v1','job':job,'rows':rows,'exact_sha256':sha(exact),
        'seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-initial_cpu,'construction':construction,
        'peak_rss_bytes_macos':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'library_sha256':hashlib.sha256(native._LIB_PATH.read_bytes()).hexdigest(),'library':str(native._LIB_PATH),
        'dependency_versions':{'torch':torch.__version__,'numpy':np.__version__,'python':sys.version,'executable':sys.executable},
        'phase_counts':dict(collections.Counter(r['exact'].get('phase','native_root') for r in rows)),
        'sooli_history_modes':dict(collections.Counter('C' if r['exact'].get('sooli_before',[0])[0]==0 else 'O' if r['exact']['sooli_before'][2] else 'P' for r in rows if 'sooli_before' in r['exact']))}
    if not rows: raise RuntimeError('Empty qualification is invalid')
    with args.out.open('x') as f: json.dump(result,f,indent=2,allow_nan=False)
    print(json.dumps({'job':job['id'],'cpu_seconds':result['cpu_seconds'],'rows':len(rows),'phases':result['phase_counts']}),flush=True)
    signal.alarm(0)


if __name__=='__main__': main()
