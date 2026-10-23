"""Check the PyTorch-free hosted controller against the published WASM controller."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import sys
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--reference',type=Path,default=Path(__file__).with_name('compact-reference.json'))
p.add_argument('--report',type=Path)
p.add_argument('--require-host-limits',action='store_true')
p.add_argument('--no-torch',action='store_true')
a=p.parse_args()
limits={}
if a.require_host_limits:
    if sys.platform!='linux':p.error('host check requires Linux cgroup limits')
    cgroup=Path('/sys/fs/cgroup')
    cpu=(cgroup/'cpu.max').read_text().split();memory=(cgroup/'memory.max').read_text().strip()
    if cpu[0]=='max' or int(cpu[0])/int(cpu[1])>0.5 or memory=='max' or int(memory)>512*2**20:
        p.error('host check requires at most 0.5 CPU and 512 MiB')
    limits={'cpu.max':' '.join(cpu),'memory.max':memory,
            'memory.events.before':(cgroup/'memory.events').read_text()}
from tuppi_ai.compact import CompactController
from tuppi_ai.bridge import action_id, engine_action, obs_from_player_observation
from tuppi_engine import (ExplicitDeal,apply_match_action,begin_explicit_deal,create_match,
                          match_observation_for)
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore,RulesetId
from tuppi_rules.cards import card_from_index

fixture=json.loads(a.reference.read_text())
assert fixture['schema']=='tuppi.hosted.compact_reference.v1'
controller=CompactController();rows=[];phases=set()
try:
    with trusted_transitions():
        for test in fixture['cases']:
            cards=[card_from_index(i) for i in test['cards']]
            state=begin_explicit_deal(create_match(initial_score=MatchScore(*test['score']),
                initial_dealer=test['dealer'],match_ref='compact-'+test['name'],
                ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=test['dealer'],hands=tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))))
            for action in test.get('prefix',[]):
                state=apply_match_action(state,engine_action(action,state.current_actor))
            observation=match_observation_for(state,state.current_actor)
            expected=test['expected'];seat=state.current_actor
            native=obs_from_player_observation(observation)
            assert hashlib.sha256(bytes(native)).hexdigest()==expected['observation'],test['name']+' observation'
            ids=[action_id(v) for v in observation.legal_actions]
            if len(ids)>1:
                invalid=(ctypes.c_int32*len(ids))(*([ids[0]]*len(ids)))
                before=[controller.lib.tb_context(seat,f) for f in range(3)]
                assert controller.lib.tb_choose_observation(ctypes.byref(native),invalid,len(ids))==-2
                assert before==[controller.lib.tb_context(seat,f) for f in range(3)]
            started,cpu=time.perf_counter(),time.process_time()
            action,context,values=controller.choose(observation,expected['before'][seat],test['humanSeats'])
            elapsed,used=time.perf_counter()-started,time.process_time()-cpu
            assert action_id(action)==expected['action'],test['name']+' action'
            assert context==expected['after'][seat],test['name']+' cursor'
            wanted={int(k):v for k,v in expected['values'].items()}
            assert values.keys()==wanted.keys(),test['name']+' actions priced'
            error=max((abs(values[k]-wanted[k]) for k in values),default=0.0)
            assert error<=2e-6,(test['name'],error)
            # Repeating a restored cursor after other seats/roots must be exact.
            if test['name'] in ('nolo-late','sooli-5'):
                again=controller.choose(observation,expected['before'][seat],test['humanSeats'])
                assert again==(action,context,values),test['name']+' repeat'
            phases.add(test['phase'])
            row={'name':test['name'],'phase':test['phase'],'action':action_id(action),
                 'context':context,'wall_s':elapsed,'cpu_s':used,'max_value_error':error}
            rows.append(row);print(json.dumps(row),flush=True)
finally:
    controller.close()
assert phases=={0,1,3,4,5,6},phases
assert 'torch' not in sys.modules
if a.no_torch:assert importlib.util.find_spec('torch') is None
if limits:
    limits['memory.events.after']=(cgroup/'memory.events').read_text()
    assert limits['memory.events.before']==limits['memory.events.after']
    limits['memory.peak']=(cgroup/'memory.peak').read_text().strip()
peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
result={'passed':True,'worlds':1024,'inference':8,'cases':rows,'phases':sorted(phases),
        'reference_sha256':hashlib.sha256(a.reference.read_bytes()).hexdigest(),
        'models_sha256':controller.model_sha256,'torch_imported':False,
        'peak_rss_bytes':peak if sys.platform=='darwin' else peak*1024,'host_limits':limits,
        'scope':'Frozen synthetic root parity and cost; not match strength or provider capacity'}
if a.report:a.report.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
