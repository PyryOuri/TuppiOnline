"""Bounded exact DD reward oracle and immutable-weight/controller checks."""
import argparse
import base64
import ctypes as C
import json
from pathlib import Path
import random
import struct
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--reference',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
torch.set_num_threads(1)
from tuppi_ai import model,native
from tuppi_ai.best import best_agents

native.lib.tc_dd_reward_bucket.argtypes=[C.POINTER(native.TcDeal),C.POINTER(C.c_float)]
native.lib.tc_dd_reward_bucket.restype=C.c_float
rng=random.Random('compact128-port-dd-oracle-v1')
checks=0;cells=set();contracts=set();remaining=set();partials=set()
for index in range(56):
    cards=list(range(52));rng.shuffle(cards)
    hands=[sum(1<<card for card in cards[seat*13:(seat+1)*13]) for seat in range(4)]
    cell=index%25;score=(0,0) if cell==0 else (4*cell,0) if cell<13 else (0,4*(cell-12))
    contract=index%2;tail=1+(index//2)%7;partial=(index//7)%4
    deal=native.new_deal(hands,index%4,*score,ruleset=3)
    while deal.phase!=native.PH_PLAY or deal.n_played<52-4*tail+partial:
        legal=native.legal(deal)
        if deal.phase==native.PH_SHOW:
            legal=[action for action in legal if (104<=action<156 if contract else 52<=action<104)]
        action=156 if deal.phase==native.PH_SOOLI_OFFER else rng.choice(legal)
        assert native.lib.tc_apply(C.byref(deal),action)==0
    assert deal.contract==contract
    exact=native.dd_team0_tricks(deal)
    # Flat, arbitrary nonmonotonic and actual step-shaped reward maps.
    for payoff in ([0.25]*14,[rng.uniform(-1,1) for _ in range(14)],[-0.75 if t<7 else 0.625 for t in range(14)]):
        values=(C.c_float*14)(*payoff)
        actual=native.lib.tc_dd_reward_bucket(C.byref(deal),values)
        assert struct.pack('f',actual)==struct.pack('f',values[exact]),(index,exact,actual)
        checks+=1
    cells.add(score);contracts.add(contract);remaining.add(13-(deal.n_played//4));partials.add(deal.n_played%4)

root=Path(__file__).resolve().parents[1]
reference=json.loads(args.reference.read_text())
features=np.frombuffer(base64.b64decode(reference['inference']['features_base64']),dtype=np.uint8).reshape(reference['inference']['rows'],-1)
batch_reports=[]
for filename in ('vrpo1_actor_0504.pt','vrpo3_final.pt'):
    mlp=native.Mlp(model.load(root/'models'/filename,'cpu'))
    full=mlp.forward(features)
    mismatches={}
    for size in (1,2,3,7,31,32,33,127,128,129,257):
        rows=np.arange(size)%len(features)
        actual=mlp.forward(features[rows])
        mismatches[str(size)]=int(np.count_nonzero(actual.view(np.uint32)!=full[rows].view(np.uint32)))
    batch_reports.append({'model':filename,'mismatched_float32_values_by_batch_size':mismatches})

agents=best_agents(worlds=128)
assert len({id(agent.searcher.mlp) for agent in agents.values()})==1
assert len({agent.searcher.env._h for agent in agents.values()})==4
assert len({id(agent.searcher.rng) for agent in agents.values()})==4
assert all(getattr(agent.searcher.env,'_team_mlp',None) is None for agent in agents.values())
reference_agents=best_agents(worlds=128,speedups=False)
assert len({id(agent.searcher.mlp) for agent in reference_agents.values()})==4
assert all(agent.searcher.env._team_mlp is not None for agent in reference_agents.values())
report={'passed':True,'dd_oracle':{'checks':checks,'positions':56,'score_cells':len(cells),'contracts':sorted(contracts),
    'remaining_tricks':sorted(remaining),'partial_trick_sizes':sorted(partials)},'batch_invariance':batch_reports,
    'factory':{'one_shared_immutable_rollout_model':True,'four_distinct_environments_and_rngs':True,'reference_factory_retains_separate_models':True},
    'scope':'Exact reward and controller ownership checks. Batch differences are reported, never hidden or padded; no strength claim.'}
args.out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
