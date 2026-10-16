"""Research-only comparison of the owner's confirmed supported-card RAMI rule.

Run using the existing tuppi-v2 environment. All outputs stay in this directory.
No bot, engine, model, training, or live-server source is modified.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "TuppiAI"))
from tuppi_ai import native, model
from tuppi_ai.best import ANCHOR, EQUITY
from tuppi_ai.equity import Equity


def supported(hand: int) -> tuple[int, int, list[int]]:
    counts = []
    for suit in range(4):
        bits = (int(hand) >> (13 * suit)) & 8191
        length = bits.bit_count()
        # rank r needs 14-r OTHER same-suit cards: length-1 >= 14-r.
        counts.append(sum(bool(bits & (1 << rank_index))
                          for rank_index in range(max(0, 13-length), 13)))
    return sum(counts), sum(n > 0 for n in counts), counts


def rule(hand: int, threshold: int = 5, suits: int = 3) -> bool:
    n, k, _ = supported(hand)
    return n >= threshold and k >= suits


def masks(index: int, seed: str) -> tuple[int, ...]:
    deck = list(range(52))
    random.Random(f"{seed}|deal|{index}").shuffle(deck)
    return tuple(sum(1 << c for c in deck[13*s:13*(s+1)]) for s in range(4))


def clone(deal):
    return native.TcDeal.from_buffer_copy(bytes(deal))


def apply(deal, action):
    if native.lib.tc_apply(C.byref(deal), int(action)):
        raise RuntimeError(f"illegal native action {action}")


def shadow(hand_masks, dealer, position):
    d = native.new_deal(hand_masks, dealer, ruleset=3)
    for _ in range(position):
        choices = [a for a in native.legal(d) if 52 <= a < 104]
        if not choices:
            return None
        apply(d, choices[0])
    return d


def summary(values):
    x = list(map(float, values))
    if not x:
        return {"n": 0}
    mu = statistics.mean(x)
    se = statistics.stdev(x) / math.sqrt(len(x)) if len(x) > 1 else 0.
    return {"n": len(x), "mean": mu, "se": se, "ci95": [mu-1.96*se, mu+1.96*se]}


def write(name, obj):
    (HERE / name).write_text(json.dumps(obj, indent=2))


def setup():
    torch.set_num_threads(2)
    native.set_showing_fix(True)
    net = model.load(ANCHOR, "cpu")
    return net, native.Mlp(net), Equity.load(EQUITY)


def policy_actions(net, feat, mask):
    with torch.no_grad():
        q = net(torch.from_numpy(feat)).numpy()
    return np.where(mask, q, -np.inf).argmax(1).astype(np.int32), q


def validation(net, mlp, equity, count=16):
    from tuppi_engine import (ExplicitDeal, create_match, begin_explicit_deal,
                              apply_match_action, match_observation_for)
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import card_from_index
    from tuppi_ai.bridge import action_id, obs_from_player_observation, engine_action
    actions_checked, numerical_max, policy_ties = 0, 0., 0
    with trusted_transitions():
        for i in range(count):
            h, dealer = masks(i, "rami-legs-validation-v1"), i % 4
            hands = tuple(tuple(card_from_index(c) for c in range(52) if m & (1<<c)) for m in h)
            state = begin_explicit_deal(create_match(initial_score=MatchScore(0,0),
                    initial_dealer=dealer, match_ref="rami-legs-validation",
                    ruleset_id=RulesetId.PROJECT_TARGET_V3), ExplicitDeal(dealer=dealer,hands=hands))
            d = native.new_deal(h, dealer, ruleset=3)
            while state.phase in ACTIVE_PHASES:
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                no = native.observe(d, seat)
                py = obs_from_player_observation(obs)
                assert d.cur == seat and d.phase == py.phase
                ids = [action_id(a) for a in obs.legal_actions]
                assert sorted(ids) == sorted(native.legal(d))
                feat = native.encode(no, encoder=net.encoder)[None]
                assert np.array_equal(feat[0], native.encode(py, encoder=net.encoder))
                if d.phase == native.PH_SOOLI_OFFER:
                    a = native.ACT_SOOLI_DECLINE  # PolicyAgent's documented SooliFallbackAgent.
                else:
                    assert d.phase in (native.PH_SHOW, native.PH_PLAY)
                    with torch.no_grad():
                        q = net(torch.from_numpy(feat))[0].numpy()
                    nq = mlp.forward(feat)[0]
                    numerical_max = max(numerical_max, float(np.max(abs(q-nq))))
                    a = max(ids, key=lambda x: (float(q[x]), -x))
                    na = max(ids, key=lambda x: (float(nq[x]), -x))
                    policy_ties += a != na
                apply(d, a)
                state = apply_match_action(state, engine_action(a, seat))
                actions_checked += 1
            r = state.completed_deals[-1].public_result
            assert d.winner_team == r.deal_score.winner_team.value
            assert d.points == r.deal_score.points and bool(d.stolen) == r.deal_score.stolen_rami
            assert tuple(d.team_tricks) == tuple(r.team_tricks)
            assert d.contract == (r.contract.value == "RAMI")
            assert d.declarer == (-1 if r.declarer is None else r.declarer)
            assert (r.score_before.as_tuple() == (0,0))
    assert supported((1<<12)|(1<<11))[:2] == (2,1)  # AK
    assert supported((1<<11)|(1<<10)|(1<<0))[:2] == (2,1)  # KQx
    assert supported((1<<10)|(1<<1)|(1<<0))[:2] == (1,1)  # Qxx
    assert supported(sum(1<<i for i in range(9,13)))[:2] == (4,1)  # AKQJ
    out = {"deals":count,"actions_checked":actions_checked,"max_native_torch_logit_difference":numerical_max,
           "native_torch_action_disagreements":policy_ties,"ruleset":"project_target_v3", "passed":True}
    write("validation.json", out)
    print("validation", json.dumps(out), flush=True)


def bids(net, mlp, equity, n, seed):
    rows, t0 = [], time.monotonic()
    for start in range(0,n,256):
        states, metadata = [], []
        for i in range(start,min(n,start+256)):
            h, dealer = masks(i,seed), i%4
            for k in range(4):
                d = shadow(h,dealer,k)
                if d is None: continue
                hand = h[d.cur]
                total, suits, counts = supported(hand)
                states.append(d)
                metadata.append({"deal":i,"position":k,"seat":int(d.cur),"dealer":dealer,
                    "hand_mask":hand,"supported":total,"supported_suits":suits,"by_suit":counts,
                    "rule_rami":rule(hand)})
        env = native.Env(len(states),0,equity.table,single_deal=True,encoder=net.encoder)
        for j,d in enumerate(states): env.set_state(j,d)
        feat,mask,seat,phase = env.observe()
        acts,q = policy_actions(net,feat,mask)
        for j,(row,a) in enumerate(zip(metadata,acts)):
            row.update(policy_action=int(a),policy_rami=bool(a>=104))
            for name,lo,hi in (("policy_nolo",52,104),("policy_rami_card",104,156)):
                legal_ids=[int(c) for c in np.flatnonzero(mask[j]) if lo<=c<hi]
                row[name]=max(legal_ids,key=lambda c:(float(q[j,c]),-c)) if legal_ids else None
            rows.append(row)
        if (start//256)%4 == 0:
            print(f"bids {min(n,start+256)}/{n}; {time.monotonic()-t0:.1f}s",flush=True)
    result = {"deals":n,"bids":len(rows),"seed":seed,"ruleset":"project_target_v3","scores":[0,0],
              "seconds":time.monotonic()-t0,"rows":rows}
    write("policy_bids.json", result)
    agree=sum(r["rule_rami"]==r["policy_rami"] for r in rows)/len(rows)
    print("bids complete", json.dumps({"bids":len(rows),"agreement":agree,
        "rule_rami_rate":sum(r["rule_rami"] for r in rows)/len(rows),
        "policy_rami_rate":sum(r["policy_rami"] for r in rows)/len(rows)}),flush=True)


def fast_games(net, mlp, equity, n, seed, chunk):
    """Three bidding policies, identical VRPO3 play, eight duplicate legs/base.

    Arm 0: VRPO3 on all seats. Arm 1: force RAMI only when the rule qualifies.
    Arm 2: RAMI iff qualified, otherwise NOLO (a separate, stronger assumption).
    Within the chosen contract, both use VRPO3's favourite legal shown card.
    All actors get observation-only inputs; policy sooli fallback declines.
    """
    out, t0 = [], time.monotonic()
    for start in range(0,n,chunk):
        records, states = [], []
        for i in range(start,min(n,start+chunk)):
            base = masks(i,seed)
            for rotation in range(4):
                h=tuple(base[(s-rotation)%4] for s in range(4))
                for team in range(2):
                    for arm in range(3):
                        states.append(native.new_deal(h,0,ruleset=3))
                        records.append({"deal":i,"rotation":rotation,"team":team,"arm":arm,
                            "hands":h,"rule_triggers":0,"changed_bids":0})
        env=native.Env(len(states),0,equity.table,single_deal=True,encoder=net.encoder)
        for j,d in enumerate(states): env.set_state(j,d)
        complete=np.zeros(len(states),bool)
        steps=0
        while not complete.all():
            feat,mask,seat,phase=env.observe()
            acts=np.zeros(len(states),np.int32)
            normal=np.flatnonzero((phase==native.PH_SHOW)|(phase==native.PH_PLAY))
            if len(normal):
                chosen,q=policy_actions(net,feat[normal],mask[normal])
                acts[normal]=chosen
                for z,j in enumerate(normal):
                    row=records[j]
                    if phase[j]!=native.PH_SHOW or row["arm"]==0 or seat[j]%2!=row["team"]: continue
                    want=rule(row["hands"][seat[j]])
                    if row["arm"]==1 and not want: continue
                    row["rule_triggers"]+=want
                    ids=np.flatnonzero(mask[j])
                    candidates=[a for a in ids if (a>=104)==want]
                    if candidates:
                        a=max(candidates,key=lambda x:(float(q[z,x]),-int(x)))
                        row["changed_bids"]+=int((a>=104)!=(acts[j]>=104))
                        acts[j]=a
            offers=np.flatnonzero(phase==native.PH_SOOLI_OFFER)
            acts[offers]=native.ACT_SOOLI_DECLINE
            assert not np.any(np.isin(phase,[native.PH_SOOLI_GIVE,native.PH_SOOLI_RETURN,native.PH_SOOLI_PLAY]))
            assert env.step(acts)==0
            finished=np.flatnonzero(env.done)
            for j in finished:
                row=records[j]; d=env.deal(int(j)); team=row["team"]
                row.update(equity=float(env.delta0[j])*(1 if team==0 else -1),
                    won=int(d.winner_team)==team,points=int(d.points)*(1 if int(d.winner_team)==team else -1),
                    tricks=int(d.team_tricks[team]),contract="RAMI" if d.contract else "NOLO",
                    declared=int(d.declarer)>=0 and int(d.declarer)%2==team,stolen=bool(d.stolen))
            complete[finished]=True
            steps+=1
            assert steps<=60
        for r in records: del r["hands"]
        out.extend(records)
        print(f"games {min(n,start+chunk)}/{n}; {time.monotonic()-t0:.1f}s",flush=True)
        write("policy_games_partial.json",{"seed":seed,"completed_base_deals":min(n,start+chunk),"rows":out})
    paired={}
    for r in out:
        key=(r["deal"],r["rotation"],r["team"])
        paired.setdefault(key,{})[r["arm"]]=r
    base={}
    for (i,rot,team),arms in paired.items():
        assert set(arms)=={0,1,2}
        base.setdefault(i,{1:[],2:[]})
        for arm in (1,2): base[i][arm].append(arms[arm]["equity"]-arms[0]["equity"])
    means={arm:[statistics.mean(base[i][arm]) for i in sorted(base)] for arm in (1,2)}
    result={"seed":seed,"base_deals":n,"played_games":len(out),"seconds":time.monotonic()-t0,
            "trigger_minus_policy_equity":summary(means[1]),"full_rule_minus_policy_equity":summary(means[2]),
            "rows":out,"base_differences":means}
    write("policy_games.json",result)
    print("games complete",json.dumps({k:v for k,v in result.items() if k not in ("rows","base_differences")}),flush=True)


def branches(net, mlp, equity, seed, chunk=256):
    """Same qualified hand, RAMI versus pass, with fast strong policy continuation.

    Previous seats are forced to NOLO with their own preferred legal cards.
    After the tested bid all remaining bids/play follow VRPO3. Passing may
    therefore result in another seat declaring RAMI; it does not force NOLO.
    """
    rows=json.loads((HERE/"policy_bids.json").read_text())["rows"]
    by_position={(r["deal"],r["position"]):r for r in rows}
    qualified=[r for r in rows if r["rule_rami"]]
    out=[];t0=time.monotonic()
    for start in range(0,len(qualified),chunk):
        states=[];records=[]
        for row in qualified[start:start+chunk]:
            h=masks(row["deal"],seed)
            d=native.new_deal(h,row["dealer"],ruleset=3)
            for k in range(row["position"]): apply(d,by_position[(row["deal"],k)]["policy_nolo"])
            assert int(d.cur)==row["seat"]
            for contract,key in ((0,"policy_nolo"),(1,"policy_rami_card")):
                c=clone(d);apply(c,row[key]);states.append(c)
                records.append({k:row[k] for k in ("deal","position","seat","dealer","supported","supported_suits","policy_rami","hand_mask")})
                records[-1]["forced_bid"]="RAMI" if contract else "NOLO"
        env=native.Env(len(states),0,equity.table,single_deal=True,encoder=net.encoder)
        for j,d in enumerate(states): env.set_state(j,d)
        complete=np.zeros(len(states),bool);steps=0
        while not complete.all():
            feat,mask,seat,phase=env.observe()
            acts=np.zeros(len(states),np.int32)
            normal=np.flatnonzero((phase==native.PH_SHOW)|(phase==native.PH_PLAY))
            if len(normal): acts[normal]=policy_actions(net,feat[normal],mask[normal])[0]
            acts[phase==native.PH_SOOLI_OFFER]=native.ACT_SOOLI_DECLINE
            assert env.step(acts)==0
            for j in np.flatnonzero(env.done):
                r=records[j];d=env.deal(int(j));team=r["seat"]%2
                r.update(equity=float(env.delta0[j])*(1 if team==0 else -1),
                    won=int(d.winner_team)==team,points=int(d.points)*(1 if d.winner_team==team else -1),
                    tricks=int(d.team_tricks[team]),contract="RAMI" if d.contract else "NOLO",
                    declarer=int(d.declarer),stolen=bool(d.stolen))
            complete[env.done.astype(bool)]=True;steps+=1;assert steps<=60
        out.extend(records)
        if (start//chunk)%4==0:print(f"branches {min(len(qualified),start+chunk)}/{len(qualified)}; {time.monotonic()-t0:.1f}s",flush=True)
    write("policy_branches.json",{"seed":seed,"qualified_hands":len(qualified),"played_games":len(out),
        "seconds":time.monotonic()-t0,"rows":out})
    print(f"branches complete {len(out)} games",flush=True)


def search_bids(n, seed, worlds):
    from tuppi_ai.best import best_agents
    from tuppi_ai.bridge import action_id
    from tuppi_engine import (ExplicitDeal,create_match,begin_explicit_deal,apply_match_action,match_observation_for)
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import card_from_index, card_to_index
    torch.set_num_threads(1)
    native.set_rollout_chunk(128)
    agents=best_agents(worlds=worlds)
    for agent in agents.values(): agent.reseed=True
    candidates=json.loads((HERE/"policy_bids.json").read_text())["rows"]
    # Prespecified separate strata: rule-positive and rule-negative, all positions balanced.
    selected=[]
    for k in range(4):
        for positive in (True,False):
            bucket=[r for r in candidates if r["position"]==k and r["rule_rami"]==positive]
            random.Random(f"{seed}|search-stratum|{k}|{positive}").shuffle(bucket)
            selected.extend(bucket[:n//8])
    selected.sort(key=lambda r:(r["deal"],r["position"]))
    out=[];t0=time.monotonic()
    with trusted_transitions():
        for ix,row in enumerate(selected):
            h=masks(row["deal"],seed);dealer=row["dealer"]
            hands=tuple(tuple(card_from_index(c) for c in range(52) if m&(1<<c)) for m in h)
            state=begin_explicit_deal(create_match(initial_score=MatchScore(0,0),initial_dealer=dealer,
                match_ref="rami-legs-search",ruleset_id=RulesetId.PROJECT_TARGET_V3),ExplicitDeal(dealer=dealer,hands=hands))
            for _ in range(row["position"]):
                obs=match_observation_for(state,state.current_actor)
                ids=sorted([a for a in obs.legal_actions if 52<=action_id(a)<104],key=action_id)
                state=apply_match_action(state,ids[0])
            seat=state.current_actor;obs=match_observation_for(state,seat)
            assert sum(1<<card_to_index(c) for c in obs.own_hand)==row["hand_mask"]
            agent=agents[seat]
            # Fresh-deal configuration, explicitly reset history-sensitive sooli options.
            agent.searcher.env.set_sooli(0,False,False,0.)
            action=agent.choose_action(obs)
            vals=agent.last_values or {}
            rv=max((v for a,v in vals.items() if a>=104),default=None)
            nv=max((v for a,v in vals.items() if 52<=a<104),default=None)
            result={**row,"worlds":worlds,"search_action":action_id(action),"search_rami":action.declared_contract.value=="RAMI",
                    "v_rami":rv,"v_nolo":nv,"values":{str(a):v for a,v in vals.items()}}
            if rv is not None and nv is not None:
                result["rami_minus_nolo_searched"]=rv-nv
                result["rule_value_minus_bot_value"]=max((v for a,v in vals.items() if (a>=104)==row["rule_rami"]),default=0.)-vals[action_id(action)]
            out.append(result)
            write(f"search_bids_w{worlds}.json",{"seed":seed,"requested":n,"seconds":time.monotonic()-t0,"rows":out})
            if ix%8==0: print(f"search W{worlds} {ix+1}/{len(selected)}; {time.monotonic()-t0:.1f}s",flush=True)
    print(f"search W{worlds} complete {len(out)}",flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["validate","bids","games","branches","search"])
    p.add_argument("--n",type=int,default=8192)
    p.add_argument("--seed",default="rami-five-legs-20261004-v1")
    p.add_argument("--chunk",type=int,default=128)
    p.add_argument("--worlds",type=int,default=128)
    a=p.parse_args()
    if a.mode=="search": search_bids(a.n,a.seed,a.worlds);return
    net,mlp,equity=setup()
    if a.mode=="validate": validation(net,mlp,equity,a.n)
    elif a.mode=="bids": bids(net,mlp,equity,a.n,a.seed)
    elif a.mode=="games": fast_games(net,mlp,equity,a.n,a.seed,a.chunk)
    elif a.mode=="branches": branches(net,mlp,equity,a.seed,a.chunk)


if __name__=="__main__": main()
