"""Reproducible observation-only mining of an ungraded human bidding probe."""
from __future__ import annotations
import ctypes as C
from dataclasses import replace
import hashlib
import json
import random
import shutil
import sys
import time
from pathlib import Path
import numpy as np
import torch

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(ROOT/'TuppiProject-training/src'),str(ROOT/'TuppiAI')]
from tuppi_ai import native, model, best
from tuppi_ai.bridge import action_id, engine_action, obs_from_player_observation
from tuppi_engine import (ExplicitDeal,begin_explicit_deal,create_match,match_observation_for,
                         locked_bid_options,observation_to_data,action_to_data,explicit_deal_to_data)
from tuppi_rules import MatchScore,RulesetId,card_from_code,card_to_code
from tuppi_server.expert_training import _family

BANK='rami-threshold-20261004-v1'
SEED='human-rami-threshold-fresh-20261004-v1'
BANDS=[(-.030,-.010,1),(-.010,-.003,2),(-.003,0.,2),(0.,.003,2),(.003,.010,2),(.010,.030,1)]

def write(name,data):
    target=HERE/name
    temp=target.with_suffix(target.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(target)

def band(gap):
    return next((i for i,(lo,hi,quota) in enumerate(BANDS) if lo<=gap<hi),None)

def cards_for(index):
    deck=[f'{r}{s}' for s in 'HDCS' for r in ('2','3','4','5','6','7','8','9','10','J','Q','K','A')]
    random.Random(f'{SEED}|shuffle|{index}').shuffle(deck)
    return [deck[13*s:13*(s+1)] for s in range(4)]

def features(hand):
    counts=[];lengths=[];hcp=0
    for s in 'HDCS':
        ranks=[{'A':14,'K':13,'Q':12,'J':11}.get(c[:-1],int(c[:-1]) if c[:-1].isdigit() else 0)
               for c in hand if c[-1]==s]
        lengths.append(len(ranks));counts.append(sum(len(ranks)-1>=14-r for r in ranks))
        hcp+=sum(max(0,r-10) for r in ranks)
    return {'supportedCards':sum(counts),'supportedSuits':sum(c>0 for c in counts),'supportBySuit':counts,
            'suitLengths':lengths,'hcp':hcp}

def state_for(index,position):
    hands=cards_for(index);dealer=(3-position)%4
    deal=ExplicitDeal(dealer=dealer,hands=tuple(tuple(card_from_code(c) for c in h) for h in hands))
    state=begin_explicit_deal(create_match(initial_score=MatchScore(0,0),initial_dealer=dealer,
        match_ref=f'{BANK}-{index:05d}',ruleset_id=RulesetId.PROJECT_TARGET_V3),deal)
    initial=match_observation_for(state,0)
    legal=locked_bid_options(state.active_deal,0)
    teacher=replace(initial,current_actor=0,bids_locked=position,legal_actions=legal)
    learner=replace(initial,current_actor=0,bids_locked=0,legal_actions=legal)
    return state,deal,teacher,learner

def reset(agent):
    cfg=agent.sooli
    agent.searcher.env.set_sooli(cfg['belief'],False,cfg['offer_play_heur'],cfg['lam'])

def main():
    torch.set_num_threads(1)
    native.set_showing_fix(True);native.set_rollout_chunk(128)
    paths=list((ROOT/'TuppiAI/tuppi_ai').glob('*.py'))
    paths+=list(dict.fromkeys([best.ROLLOUT,best.OPPONENT_ROLLOUT,best.TEAM_ROLLOUT,best.ANCHOR,best.EQUITY,native._LIB_PATH]))
    paths+=list((ROOT/'TuppiProject-training/src/tuppi_engine').glob('*.py'))
    paths+=list((ROOT/'TuppiProject-training/src/tuppi_rules').glob('*.py'))
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    config={'worlds':1024,'screenWorlds':128,'confirmWorlds':4096,'dd':best.SOLVER_TAIL,'keep':best.KEEP,
        'keepShow':best.KEEP_SHOW,'ramiMargin':best.RAMI_MARGIN,'adaptive':best.ADAPTIVE_BIDS,
        'showingFix':True,'reseed':True,'v3SooliReset':True,'torch':torch.__version__,'seed':SEED}
    ref='bid-probe-'+hashlib.sha256(json.dumps({'hashes':hashes,'config':config},sort_keys=True).encode()).hexdigest()
    if (HERE/'provenance.json').exists():
        assert json.loads((HERE/'provenance.json').read_text())['referenceID']==ref,'source drift; create a new bank version'
    else:
        write('provenance.json',{'referenceID':ref,'hashes':hashes,'config':config,'bankID':BANK,'bands':BANDS})
        for p in paths:
            dst=HERE/'reference'/p.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    screen=best.best_agents([0],worlds=128)[0];screen.reseed=True
    confirm=best.best_agents([0],worlds=1024)[0];confirm.reseed=True
    ledger=json.loads((HERE/'screen.json').read_text()) if (HERE/'screen.json').exists() else []
    seen={r['index'] for r in ledger};t0=time.monotonic()
    # A fixed pool; broad hand-strength filter spends compute on plausible choices.
    for index in range(2400):
        if index in seen:continue
        position=index%4;hands=cards_for(index);f=features(hands[0])
        if not (9<=f['hcp']<=22 and 2<=f['supportedCards']<=7):continue
        state,deal,obs,learner=state_for(index,position)
        reset(screen);chosen=screen.choose_action(obs);v=screen.last_values
        r=max((a for a in v if a>=104),key=lambda a:v[a]);n=max((a for a in v if 52<=a<104),key=lambda a:v[a])
        ledger.append({'index':index,'position':position,**f,'screenGap':v[r]-v[n],
                       'screenAction':action_id(chosen),'screenRami':r,'screenNolo':n})
        if len(ledger)%40==0:
            write('screen.json',ledger);print(f'screen {len(ledger)} candidates; {time.monotonic()-t0:.1f}s',flush=True)
    write('screen.json',ledger)
    confirmed=json.loads((HERE/'confirmation.json').read_text()) if (HERE/'confirmation.json').exists() else []
    done={r['index'] for r in confirmed};quotas={(p,b):BANDS[b][2] for p in range(4) for b in range(6)}
    selected=[]
    for row in confirmed:
        key=(row['position'],row['band'])
        if key in quotas and sum((r['position'],r['band'])==key for r in selected)<quotas[key]:selected.append(row)
    # Round-robin through screen bands; reserve capacity for confirmation drift.
    buckets={}
    for p in range(4):
        for b in range(6):
            bucket=[r for r in ledger if r['position']==p and band(r['screenGap'])==b and r['index'] not in done]
            random.Random(f'{SEED}|candidates|{p}|{b}').shuffle(bucket);buckets[(p,b)]=bucket
    while len(selected)<40:
        progressed=False
        for key,quota in quotas.items():
            if sum((r['position'],r['band'])==key for r in selected)>=quota:continue
            if not buckets[key]:continue
            row=buckets[key].pop();progressed=True
            state,deal,obs,learner=state_for(row['index'],row['position'])
            reset(confirm);current=confirm.choose_action(obs);v=confirm.last_values
            ra=max((a for a in v if a>=104),key=lambda a:v[a]);na=max((a for a in v if 52<=a<104),key=lambda a:v[a])
            # Independent confirmation worlds; fixed representatives avoid maximizing on this sample.
            ob=obs_from_player_observation(obs)
            seed=int.from_bytes(hashlib.sha256(f'{SEED}|confirm|{row["index"]}'.encode()).digest()[:8],'little')
            rng=C.c_uint64(seed)
            samples=native.search_world_values(confirm.searcher.env,confirm.searcher.mlp,ob,[na,ra],4096,best.SOLVER_TAIL,rng)
            diff=samples[:,1]-samples[:,0];gap=float(diff.mean());se=float(diff.std(ddof=1)/np.sqrt(len(diff)))
            result={**row,'band':band(gap),'valueGap':gap,'standardError':se,'ci95':[gap-1.96*se,gap+1.96*se],
                'ramiAction':action_to_data(engine_action(ra,0)),'noloAction':action_to_data(engine_action(na,0)),
                'botAction':action_to_data(current),'vRami':float(samples[:,1].mean()),'vNolo':float(samples[:,0].mean()),
                'confirmationSeed':seed}
            confirmed.append(result);write('confirmation.json',confirmed)
            destination=(row['position'],result['band'])
            if destination in quotas and sum((r['position'],r['band'])==destination for r in selected)<quotas[destination]:
                selected.append(result)
            print(f'confirmed {len(confirmed)}; selected {len(selected)}/40; last gap {gap:+.5f}',flush=True)
        if not progressed:raise RuntimeError(f'Insufficient confirmed candidates: {[(k,q) for k,q in quotas.items() if sum((r["position"],r["band"])==k for r in selected)<q]}')
    random.Random(f'{SEED}|bank-order').shuffle(selected)
    cases=[];deals=[]
    for order,row in enumerate(selected):
        state,deal,teacher,learner=state_for(row['index'],row['position'])
        hands=[[card_to_code(c) for c in h] for h in deal.hands]
        observation=observation_to_data(learner)
        case_id=f'{BANK}-{order+1:02d}'
        gap=row['valueGap'];se=row['standardError']
        feedback={'evidence':'modelEstimate','referenceID':ref,'acceptedActions':[],'preferredAction':row['botAction'],
            'explanation':f'Jäädytetyn vahvan botin RAMI–NOLO-arvoero on {100*gap:+.2f} prosenttiyksikköä mallin otteluarvossa; 95 % otanta-alue [{100*(gap-1.96*se):+.2f}, {100*(gap+1.96*se):+.2f}]. Tämä on arvio mahdollisista piilokorteista, ei tarkka vastausavain.',
            'decidingFeature':'Oma käsi, tarjouspaikka ja 0–0-pistetilanne yhdessä.',
            'principle':'Vertaa RAMIn lisäarvoa NOLO-tarjoukseen ennen muiden käsien näkemistä.',
            'exception':'Kumppanin ja vastustajien pelitaso sekä ottelupisteet voivat muuttaa kynnystä.',
            'uncertainty':'Korttien sijainti ja jatkopeli ovat epävarmoja. Botin oma tarjous sisältää myös politiikka-ankkurin; se voi erota pelkän arvoeron etumerkistä.',
            'lines':[],'transferCaseIDs':[],'counterexampleCaseIDs':[],'fullHands':hands,'odds':None,'adjudicated':False,
            'replay':{'dealer':deal.dealer,'initialHands':hands,'initialScore':[0,0],'prefix':[]}}
        probe={'bankID':BANK,'valueGap':gap,'standardError':se,'band':row['band'],
               'supportedCards':row['supportedCards'],'supportedSuits':row['supportedSuits'],
               'ramiAction':row['ramiAction'],'noloAction':row['noloAction']}
        cases.append({'schemaVersion':'tuppi.training.case.v1','id':case_id,'familyID':_family(deal),
            'title':f'Tarjouskynnys · käsi {order+1:02d}','skill':'bidding',
            'context':'Pisteet 0–0. Muut tarjoukset ja kädet eivät näy. Valitse RAMI tai NOLO. Kuvittele oma pari ja vastapuoli vahvoiksi pelaajiksi.',
            'observation':observation,'source':{'roomCode':None,'matchRef':observation['match_ref'],
              'dealRef':observation['deal_ref'],'dealNumber':0,'decisionIndex':-1,'eventIndex':-1,'previouslySeen':False,'blindBid':True},
            'engineValidated':True,'approvedForAssessment':False,'feedback':feedback,'questions':[],
            'informationMode':'normal','bidProbe':probe})
        deals.append({'caseID':case_id,'shuffleIndex':row['index'],'shuffleSeed':f'{SEED}|shuffle|{row["index"]}',
                      'explicitDeal':explicit_deal_to_data(deal),'evaluation':row})
    pack={'schemaVersion':'tuppi.training.pack.v1','title':'RAMI-kynnys · 40 sokeaa tarjousta 0–0','cases':cases}
    assert len({c['familyID'] for c in cases})==40
    for p in range(4):
        for b in range(6):assert sum(d['evaluation']['position']==p and d['evaluation']['band']==b for d in deals)==BANDS[b][2]
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    write('rami-threshold-v1.json',pack);write('deals.json',deals)
    write('validation.json',{'passed':True,'cases':40,'families':40,'closeCalls':32,'shoulders':8,
        'positions':[10]*4,'screened':len(ledger),'confirmed':len(confirmed),'referenceID':ref,'sourceHashesUnchanged':True,
        'minGap':min(c['bidProbe']['valueGap'] for c in cases),'maxGap':max(c['bidProbe']['valueGap'] for c in cases)})
    print('bank complete: 40 distinct families',flush=True)

if __name__=='__main__':main()
