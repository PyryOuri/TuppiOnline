"""Freeze qualification dose and code identities before outcomes."""
import hashlib
import json
from pathlib import Path

OUT=Path(__file__).resolve().parent
PREP=OUT.parent/'tuppi_cheap_wins_preparation_20261014'


def main():
    variants=['reference','combo32','combo128','compact128']
    stages={'parity':[],'timing':[],'parallel':[]}
    for mode,worlds,cpu,wall in [('native_roots',16,90,120),('history_bank',128,120,150),('forced_sooli',1024,90,120)]:
        for variant in variants:
            stages['parity'].append({'id':mode+'_'+variant,'mode':mode,'variant':variant,'worlds':worlds,'parallel':False,
                'seed':'qualification-fixtures-v1','samples':0,'cpu_seconds':cpu,'wall_seconds':wall})
    # Latin rotation balances each variant's within-round position; references
    # remain in every round. Same two retained deals in all technical replicates.
    orders=[variants,variants[::-1],variants[1:]+variants[:1],variants[2:]+variants[:2],variants[3:]+variants[:3]]
    for stage,parallel,cpu,wall in [('timing',False,90,120),('parallel',True,150,180)]:
        for round_index,order in enumerate(orders,start=1):
            for variant in order:
                stages[stage].append({'id':f'r{round_index}_{variant}','mode':'games','variant':variant,'worlds':1024,'parallel':parallel,
                    'seed':'cw-w1024-qualification-v1','samples':2,'cpu_seconds':cpu,'wall_seconds':wall,'round':round_index})
    names=['BUILD.json','FIXTURES.json','build.py','bindings.py','worker.py','run.py','create_plan.py']
    plan={'schema':'tuppi.speed_qualification.plan.v1','execution_default':'preview',
          'base_package_sha256':hashlib.sha256((PREP/'PACKAGE.json').read_bytes()).hexdigest(),
          'inputs':{name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in names},'stages':stages,
          'budgets':{stage:{'cpu_seconds':sum(x['cpu_seconds'] for x in jobs),'wall_seconds':sum(x['wall_seconds'] for x in jobs)} for stage,jobs in stages.items()},
          'selection':'Require all exact comparisons. Use repeated serial CPU and native-parallel latency; no strength endpoint or saved-CPU world increase.'}
    with (OUT/'PLAN.json').open('x') as f: json.dump(plan,f,indent=2)
    print(json.dumps({'jobs':{k:len(v) for k,v in stages.items()},'budgets':plan['budgets']},indent=2))


if __name__=='__main__': main()
