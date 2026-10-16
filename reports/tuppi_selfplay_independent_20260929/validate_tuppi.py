"""Small real-v3 differential/estimator validation; no training or live imports."""
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT/'vendor'))
from tuppi_engine import (ExplicitDeal, create_match, begin_explicit_deal,
                         apply_match_action, match_observation_for)
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_rules import MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK
import native_binding as nb
from bridge import action_id, mask_of, obs_from_player_observation, _PHASE
from estimators import masked_probabilities, expected_value, targets, actor_advantages, clipped_surrogate

L = nb.lib
L.tc_struct_sizes.argtypes = [C.POINTER(C.c_int)]
L.tc_deal_init_v.argtypes = [C.POINTER(nb.TcDeal), C.POINTER(C.c_uint64), C.c_int, C.c_int, C.c_int, C.c_int]
L.tc_legal.argtypes = [C.POINTER(nb.TcDeal), C.POINTER(C.c_int)]
L.tc_apply.argtypes = [C.POINTER(nb.TcDeal), C.c_int]
L.tc_observe.argtypes = [C.POINTER(nb.TcDeal), C.c_int, C.POINTER(nb.TcObs)]
L.tc_feature_dim_v.argtypes = [C.c_int]
L.tc_encode_v.argtypes = [C.POINTER(nb.TcObs), C.POINTER(C.c_uint8), C.c_int]
L.tc_next_score.argtypes = [C.POINTER(C.c_uint8), C.c_int, C.c_int, C.POINTER(C.c_uint8)]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def legal(d):
    buf = (C.c_int*210)()
    n = L.tc_legal(C.byref(d), buf)
    require(0 < n <= 210, 'invalid legal action count')
    return list(buf[:n])


def encode(obs):
    a = (C.c_uint8*L.tc_feature_dim_v(2))()
    L.tc_encode_v(C.byref(obs), a, 2)
    return bytes(a)


def clone(d):
    return nb.TcDeal.from_buffer_copy(bytes(d))


def step(d, a):
    nxt = clone(d)
    require(L.tc_apply(C.byref(nxt), a) == 0, 'native transition rejected')
    return nxt


def utility(d):
    return 1.0 if d.winner_team == 0 else -1.0


def exact_suffix(d):
    """Exhaustive uniform-policy value in a REAL Tuppi late-game state."""
    if d.phase == nb.PH_DONE:
        return utility(d)
    acts = legal(d)
    return sum(exact_suffix(step(d,a)) for a in acts)/len(acts)


def suffix_paths(d):
    if d.phase == nb.PH_DONE:
        return [(1.0, [], [], [])]
    acts = legal(d)
    q = {a:exact_suffix(step(d,a)) for a in acts}
    v = sum(q.values())/len(q)
    out=[]
    for a in acts:
        nxt=step(d,a)
        for prob, rewards, qs, vs in suffix_paths(nxt):
            out.append((prob/len(acts), [utility(nxt) if nxt.phase==nb.PH_DONE else 0.0]+rewards,
                        [q[a]]+qs,[v]+vs))
    return out


def run():
    start=time.perf_counter()
    sizes=(C.c_int*2)(); L.tc_struct_sizes(sizes)
    require(list(sizes)==[C.sizeof(nb.TcDeal), C.sizeof(nb.TcObs)], 'ABI mismatch')
    phases=set(); trajectory_rows=[]; suffix_reports=[]; deals=[]
    for index in range(12):
        rng=random.Random(902900+index)
        cards=list(FULL_DECK); rng.shuffle(cards)
        hands=tuple(tuple(cards[13*s:13*(s+1)]) for s in range(4))
        score=(0,0) if index<4 else ((48,0) if index<8 else (0,48))
        dealer=index%4; mode=('nolo','rami','sooli')[index%3]
        state=begin_explicit_deal(create_match(initial_score=MatchScore(*score),initial_dealer=dealer,
            match_ref=f'isolated-{index}',ruleset_id=RulesetId.PROJECT_TARGET_V3),ExplicitDeal(dealer=dealer,hands=hands))
        d=nb.TcDeal(); masks=(C.c_uint64*4)(*[mask_of(h) for h in hands])
        L.tc_deal_init_v(C.byref(d), masks,dealer,*score,3)
        # Same own hand, different hidden deal -> identical bidding actor encoding.
        alternate=clone(d); alternate.hand[(d.cur+1)%4],alternate.hand[(d.cur+2)%4]=alternate.hand[(d.cur+2)%4],alternate.hand[(d.cur+1)%4]
        obs1=nb.TcObs(); obs2=nb.TcObs()
        L.tc_observe(C.byref(d),d.cur,C.byref(obs1)); L.tc_observe(C.byref(alternate),d.cur,C.byref(obs2))
        require(encode(obs1)==encode(obs2),'hidden initial hands changed actor features')
        require(bytes(d)!=bytes(alternate),'hidden-state intervention ineffective')
        rows=[]; suffix=None
        while state.phase in ACTIVE_PHASES:
            require(len(rows)<100,'trajectory exceeded bound')
            seat=state.current_actor; phases.add(state.phase.value)
            obs=match_observation_for(state,seat)
            actions=list(obs.legal_actions); ids=[action_id(a) for a in actions]
            require(d.cur==seat and d.phase==_PHASE[state.phase],'actor/phase mismatch')
            require(sorted(ids)==sorted(legal(d)),'legal action mismatch')
            for s in range(4):
                native_obs=nb.TcObs(); L.tc_observe(C.byref(d),s,C.byref(native_obs))
                reference_obs=obs_from_player_observation(match_observation_for(state,s))
                require(bytes(native_obs)==bytes(reference_obs),'observation mismatch')
                require(encode(native_obs)==encode(reference_obs),'encoding mismatch')
            # Deliberate coverage controls, not a strength policy or training dataset.
            allowed=ids
            if d.phase==nb.PH_SHOW:
                allowed=[a for a in ids if (a<104 if mode=='nolo' else a>=104)]
            elif d.phase==nb.PH_SOOLI_OFFER:
                allowed=[nb.ACT_SOOLI_ACCEPT if mode=='sooli' else nb.ACT_SOOLI_DECLINE]
            probs=masked_probabilities([0.0]*210,allowed)
            chosen=rng.choices(range(210),weights=probs,k=1)[0]
            require(probs[chosen]>0 and math.isclose(sum(probs),1),'bad mask')
            require(all(probs[a]==0 for a in range(210) if a not in ids),'illegal mass')
            if d.phase==nb.PH_PLAY and d.n_played==44:
                suffix=clone(d)
            rows.append({'parent_id':f'fixture-{index}','policy_version':f'coverage-{mode}-v1',
                         'seat':seat,'phase':d.phase,'action':chosen,'old_logp':math.log(probs[chosen]),
                         'legal_actions':ids,'behavior_support':allowed,'reward_team0':0.0,
                         'actor_features_sha256':hashlib.sha256(encode(obs_from_player_observation(obs))).hexdigest()})
            require(math.isclose(math.exp(rows[-1]['old_logp']),probs[chosen]),'log probability mismatch')
            d=step(d,chosen)
            state=apply_match_action(state,actions[ids.index(chosen)])
        result=state.completed_deals[-1].public_result
        require(d.phase==nb.PH_DONE,'not complete')
        require(d.winner_team==result.deal_score.winner_team.value and d.points==result.deal_score.points,'outcome mismatch')
        require(tuple(d.team_tricks)==tuple(result.team_tricks),'trick mismatch')
        after=(C.c_uint8*2)(); ended=L.tc_next_score(d.score,d.winner_team,d.points,after)
        require(tuple(after)==result.score_after.as_tuple() and bool(ended)==result.match_terminal,'match transition mismatch')
        rows[-1]['reward_team0']=utility(d)
        rewards=[r['reward_team0'] for r in rows]; n=len(rows)
        qt,qa,ga=targets(rewards,[0.0]*n,[0.0]*(n+1),lam=1)
        require(all(x==utility(d) for x in qt+qa+ga),'zero critic must recover terminal return')
        aa=actor_advantages(qa,[r['seat'] for r in rows])
        require(all(a==(utility(d) if r['seat']%2==0 else -utility(d)) for a,r in zip(aa,rows)),'team sign mismatch')
        require(all(clipped_surrogate(r['old_logp'],r['old_logp'],a)==a for r,a in zip(rows,aa)),'identity PPO update mismatch')
        if suffix is not None:
            paths=suffix_paths(suffix); errors=[]
            require(math.isclose(sum(p[0] for p in paths),1),'suffix probability total')
            for prob,rews,qs,vs in paths:
                tq,adv,gae=targets(rews,qs,vs+[0.0],lam=1)
                require(all(math.isclose(x,y,abs_tol=1e-12) for x,y in zip(tq,qs)),'exact Q residual not zero')
                errors.append((prob,(adv[0]-(qs[0]-vs[0]))**2,(gae[0]-(qs[0]-vs[0]))**2))
            suffix_reports.append({'parent':index,'paths':len(paths),'q_advantage_mse':sum(p*q for p,q,g in errors),'gae_advantage_mse':sum(p*g for p,q,g in errors)})
        deals.append({'parent':index,'mode':mode,'steps':n,'winner':int(d.winner_team),'score_after':list(after),'match_terminal':bool(ended)})
        trajectory_rows.extend(rows)
    # Real trajectories, independently evaluated explicit finite-sum trace oracle.
    rewards=[r['reward_team0'] for r in rows]; n=len(rows)
    qs=[math.sin(i)*0.1 for i in range(n)]; vs=[math.cos(i)*0.1 for i in range(n)]+[0.0]
    for lam in [0,0.5,0.95,1]:
        tq,aq,av=targets(rewards,qs,vs,lam=lam)
        for t in range(n):
            oracle=qs[t]+sum(lam**(j-t)*(rewards[j]+vs[j+1]-qs[j]) for j in range(t,n))
            require(math.isclose(tq[t],oracle,abs_tol=1e-12),'finite-sum trace mismatch')
    try: targets([0],[0],[0,1],terminal=True)
    except ValueError: pass
    else: raise AssertionError('terminal bootstrap accepted')
    require(targets([0],[0],[0,1],terminal=False)[0]==[1],'truncation bootstrap lost')
    require(expected_value([0.25,0.75,0],[2,-2,float('nan')])==-1,'expectation/mask mismatch')
    require(math.isclose(clipped_surrogate(math.log(2),0,1),1.2),'positive clipping failed')
    require(math.isclose(clipped_surrogate(math.log(0.5),0,-1),-0.8),'negative clipping failed')
    rejected=0
    for logits, support in [([0,0],[]),([0,0],[0,0]),([0,0],[2]),([float('nan'),0],[0])]:
        try: masked_probabilities(logits,support)
        except ValueError: rejected+=1
    require(rejected==4,'malformed mask/logit accepted')
    require(any(r['gae_advantage_mse']>0 for r in suffix_reports),'no nontrivial stochastic suffix exercised')
    output={'status':'PASS','scope':'12 real v3 deals; correctness only, no learner training or strength measurement',
            'seconds':time.perf_counter()-start,'phases':sorted(phases),'rows':len(trajectory_rows),'deals':deals,'exact_real_game_suffixes':suffix_reports}
    (ROOT/'VALIDATION.json').write_text(json.dumps(output,indent=2)+'\n')
    (ROOT/'TRAJECTORIES.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in trajectory_rows))
    print(json.dumps(output,indent=2))


if __name__=='__main__': run()
