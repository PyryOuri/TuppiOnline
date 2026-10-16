"""Finite sequential qualification stages with immutable plans and attempts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

OUT=Path(__file__).resolve().parent
PREP=OUT.parent/'tuppi_cheap_wins_preparation_20261014'
PYTHON='/Users/pyryouri/.venvs/tuppi-v2/bin/python'


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def publish(p,value):
    with p.open('x') as f: json.dump(value,f,indent=2,allow_nan=False); f.write('\n')


def verify(plan):
    sys.path.insert(0,str(PREP))
    from launch import verify as verify_previous
    verify_previous()
    if digest(PREP/'PACKAGE.json')!=plan['base_package_sha256']: raise ValueError('Base package differs')
    for name,expected in plan['inputs'].items():
        if digest(OUT/name)!=expected: raise ValueError('Qualification input changed: '+name)
    build=json.loads((OUT/'BUILD.json').read_text())
    for name,record in build['libraries'].items():
        folder=OUT/'builds'/name
        if digest(folder/'libtuppi.dylib')!=record['sha256']: raise ValueError('Private binary changed')
        for filename,expected in record['sources'].items():
            if digest(folder/filename)!=expected: raise ValueError('Private source changed')


def compatible(result,reference):
    for key in ('dependency_versions',):
        if result[key]!=reference[key]: raise ValueError('Runtime identity differs')
    for key in ('mode','worlds','parallel','seed','samples'):
        if result['job'].get(key)!=reference['job'].get(key): raise ValueError('Input design differs: '+key)
    if not result['rows'] or len(result['rows'])!=len(reference['rows']): return False
    return [r['exact'] for r in result['rows']]==[r['exact'] for r in reference['rows']]


def execute(stage,plan):
    verify(plan)
    destination=OUT/'runs'/stage; destination.mkdir(parents=True,exist_ok=False)
    if stage!='parity':
        parity=json.loads((OUT/'runs/parity/status.json').read_text())
        if not parity['complete'] or not parity['all_exact']: raise ValueError('Complete parity must pass first')
    rows=[]; cpu_charge=wall_charge=0.
    for job in plan['stages'][stage]:
        if cpu_charge+job['cpu_seconds']>plan['budgets'][stage]['cpu_seconds'] or wall_charge+job['wall_seconds']>plan['budgets'][stage]['wall_seconds']:
            break
        verify(plan); attempt=destination/job['id']; attempt.mkdir()
        publish(attempt/'job.json',job)
        command=[PYTHON,'-B',str(OUT/'worker.py'),'--job',str(attempt/'job.json'),'--out',str(attempt/'result.json')]
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
        env.pop('PYTHONPATH',None); env.pop('TUPPI_CHEAP_WINS_LIBRARY',None); env.pop('TUPPI_AI_SERIAL',None)
        print('starting',job['id'],flush=True)
        before=time.perf_counter(); usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        with (attempt/'worker.log').open('x') as log:
            try:
                child=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=job['wall_seconds']+2)
                code=child.returncode
            except subprocess.TimeoutExpired: code='TIMEOUT'
        elapsed=time.perf_counter()-before; later=resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu=later.ru_utime+later.ru_stime-usage.ru_utime-usage.ru_stime
        success=code==0 and (attempt/'result.json').exists()
        cpu_charge+=child_cpu if success else job['cpu_seconds']; wall_charge+=elapsed if success else max(elapsed,job['wall_seconds'])
        row={'job':job['id'],'success':success,'returncode':code,'child_cpu_seconds':child_cpu,'wall_seconds':elapsed,
            'result_sha256':digest(attempt/'result.json') if success else None}
        rows.append(row); publish(attempt/'status.json',row)
        if not success:
            print((attempt/'worker.log').read_text()[-3500:],flush=True); break
        print('finished',job['id'],'cpu',round(child_cpu,2),flush=True)
    complete=len(rows)==len(plan['stages'][stage]) and all(r['success'] for r in rows)
    comparisons=[]
    if complete:
        jobs=plan['stages'][stage]
        for job in jobs:
            if job['variant']=='reference': continue
            reference=next(x for x in jobs if x['variant']=='reference' and x['mode']==job['mode'] and x.get('round')==job.get('round'))
            candidate=json.loads((destination/job['id']/'result.json').read_text())
            gold=json.loads((destination/reference['id']/'result.json').read_text())
            comparisons.append({'job':job['id'],'reference':reference['id'],'exact':compatible(candidate,gold)})
    record={'schema':'tuppi.speed_qualification.stage.v1','stage':stage,'complete':complete,'all_exact':complete and all(x['exact'] for x in comparisons),
        'cpu_charged_seconds':cpu_charge,'wall_charged_seconds':wall_charge,'jobs':rows,'comparisons':comparisons}
    publish(destination/'status.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in {'jobs','comparisons'}},indent=2),flush=True)
    if not complete or not record['all_exact']: raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--stage',choices=['parity','timing','parallel'],required=True)
    parser.add_argument('--execute',action='store_true'); args=parser.parse_args()
    plan=json.loads((OUT/'PLAN.json').read_text()); verify(plan)
    if args.execute: execute(args.stage,plan)
    else: print(json.dumps({'stage':args.stage,'jobs':len(plan['stages'][args.stage]),'budget':plan['budgets'][args.stage],'status':'PREVIEW'},indent=2))


if __name__=='__main__': main()
