"""Exercise the production spawned-worker protocol, including a fresh worker.

--mode 2 (default) is Heidi 1.1 with compact-reference.json; --mode 4 is Heidi 1.2
(HostedHeidiAgent(seat, mode=4)) with compact-reference-heidi12.json."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

from tuppi_ai.bridge import action_id,engine_action
from tuppi_engine import (ExplicitDeal,apply_match_action,begin_explicit_deal,create_match,match_observation_for)
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore,RulesetId
from tuppi_rules.cards import card_from_index
from tuppi_server.hosted_bot import HostedHeidiAgent,shutdown,warm


def observation_for(test):
    cards=[card_from_index(i) for i in test['cards']]
    state=begin_explicit_deal(create_match(initial_score=MatchScore(*test['score']),
        initial_dealer=test['dealer'],match_ref='worker-'+test['name'],ruleset_id=RulesetId.PROJECT_TARGET_V3),
        ExplicitDeal(dealer=test['dealer'],hands=tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))))
    with trusted_transitions():
        for action in test.get('prefix',[]):state=apply_match_action(state,engine_action(action,state.current_actor))
    return match_observation_for(state,state.current_actor)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,default=Path(__file__).with_name('compact-reference.json'))
    p.add_argument('--report',type=Path)
    p.add_argument('--no-torch',action='store_true')
    p.add_argument('--require-host-limits',action='store_true')
    p.add_argument('--mode',type=int,choices=(2,4),default=2,help='2 Heidi 1.1, 4 Heidi 1.2')
    a=p.parse_args();fixture=json.loads(a.reference.read_text());rows=[]
    bots={2:{'heidi10','heidi11'},4:{'heidi12'}}[a.mode]
    assert all(test['bot'] in bots for test in fixture['cases']),'reference bot and --mode differ'
    limits={}
    if a.require_host_limits:
        if sys.platform!='linux':p.error('host check requires Linux cgroup limits')
        cgroup=Path('/sys/fs/cgroup');cpu=(cgroup/'cpu.max').read_text().split()
        memory=(cgroup/'memory.max').read_text().strip()
        if cpu[0]=='max' or int(cpu[0])/int(cpu[1])>0.5 or memory=='max' or int(memory)>512*2**20:
            p.error('host check requires at most 0.5 CPU and 512 MiB')
        limits={'cpu.max':' '.join(cpu),'memory.max':memory,'memory.swap.max':(cgroup/'memory.swap.max').read_text().strip()}
        assert limits['memory.swap.max']=='0'
    try:
        warm()
        for test in fixture['cases']:
            obs=observation_for(test);expected=test['expected']
            agent=HostedHeidiAgent(obs.observing_seat,mode=a.mode)
            saved={**agent.checkpoint(),'context':expected['before'][agent.seat]}
            agent.restore(saved);agent.set_human_seats(test['humanSeats'])
            assert action_id(agent.choose_action(obs))==expected['action'],test['name']
            assert agent.context==expected['after'][agent.seat],test['name']+' cursor'
            rows.append({'name':test['name'],**agent.last_stats})
        shutdown();warm()
        test=fixture['cases'][0];obs=observation_for(test);agent=HostedHeidiAgent(obs.observing_seat,mode=a.mode)
        agent.restore({**agent.checkpoint(),'context':test['expected']['before'][agent.seat]})
        agent.set_human_seats(test['humanSeats'])
        assert action_id(agent.choose_action(obs))==test['expected']['action']
        assert agent.context==test['expected']['after'][agent.seat]
        assert 'torch' not in sys.modules
        if a.no_torch:assert importlib.util.find_spec('torch') is None
        report={'passed':True,'mode':a.mode,'worker_requests':len(rows)+1,'fresh_worker_repeat':True,'cases':rows,
                'worlds':1024,'inference':8,'torch_imported':False,'host_limits':limits}
        if limits:
            limits['memory.peak']=(cgroup/'memory.peak').read_text().strip()
            limits['memory.events']=(cgroup/'memory.events').read_text()
            assert 'oom_kill 0' in limits['memory.events']
        if a.report:a.report.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)
    finally:shutdown()


if __name__=='__main__':main()
