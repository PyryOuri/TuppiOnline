"""Prepared costing plans; explicit execution uses one common qualified baseline."""
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


def verify():
    sys.path.insert(0,str(PREP))
    from launch import verify as previous
    previous()
    manifest=json.loads((OUT/'PACKAGE.json').read_text())
    for name,expected in manifest['files'].items():
        if digest(OUT/name)!=expected: raise ValueError('Qualified package changed: '+name)
    if digest(PREP/'PACKAGE.json')!=manifest['base_package_sha256']: raise ValueError('Base package changed')
    actual={p.name for p in OUT.glob('*.py')}
    expected={n for n in manifest['files'] if n.endswith('.py') and '/' not in n}
    if actual!=expected: raise ValueError('Executable set changed')
    return json.loads((OUT/'QUALIFIED_BASELINE.json').read_text())


def publish(p,value):
    with p.open('x') as f: json.dump(value,f,indent=2,allow_nan=False); f.write('\n')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('command',choices=['verify','preview','run'])
    parser.add_argument('plan',type=Path,nargs='?'); parser.add_argument('--out',type=Path); parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(); baseline=verify()
    if args.command=='verify':
        print(json.dumps({'status':'VERIFIED','baseline':baseline['variant']},indent=2)); return
    if args.plan is None: raise ValueError('Plan required')
    from launch import validate_plan
    plan=json.loads(args.plan.read_text()); preview=validate_plan(plan)
    if any(j['kind'] not in {'duplicate','match_cost'} or j['arm'] not in {'baseline','hard_anchor','suit_ensemble'} for j in plan['jobs']):
        raise ValueError('Only prepared strength/match costing jobs are supported')
    preview['qualified_baseline']=baseline['variant']
    if args.command=='preview' or not args.execute:
        print(json.dumps(preview,indent=2)); return
    if args.out is None or not args.out.resolve().is_relative_to(OUT/'analysis_runs'): raise ValueError('New output under analysis_runs/ required')
    args.out.mkdir(parents=True,exist_ok=False); publish(args.out/'plan.json',plan)
    charged_cpu=charged_wall=0.; rows=[]
    for job in plan['jobs']:
        if charged_cpu+job['cpu_seconds']>plan['budget_cpu_seconds'] or charged_wall+job['wall_seconds']>plan['budget_wall_seconds']: break
        verify(); directory=args.out/job['id']; directory.mkdir()
        context={'package_sha256':digest(OUT/'PACKAGE.json'),'base_snapshot_sha256':digest(PREP/'PACKAGE.json'),
            'worlds':job['worlds'],'workers':1,'native_parallel':False,'rollout_chunk':baseline['rollout_chunk'],
            'speed_variant':baseline['variant'],'design':'4_rotations_2_teams' if job['kind']=='duplicate' else 'match_cost',
            'controller_lifecycle':'fresh_indexed_game' if job['kind']=='duplicate' else 'retained',
            'score_design':job['scores'],'sampler_fix':True,'dd_extra_nolo':0,'sooli_reset':'fresh_on_construction_only',
            'deal_id_schema':'actual_cards_index_score_dealer.v1'}
        publish(directory/'job.json',{'job':job,'context':context})
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
        env.pop('PYTHONPATH',None); env.pop('TUPPI_CHEAP_WINS_LIBRARY',None); env.pop('TUPPI_AI_SERIAL',None)
        start=time.perf_counter(); usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        with (directory/'worker.log').open('x') as log:
            try:
                child=subprocess.run([PYTHON,'-B',str(OUT/'strength_worker.py'),'--job',str(directory/'job.json'),'--out',str(directory/'result.json')],
                    env=env,stdout=log,stderr=subprocess.STDOUT,timeout=job['wall_seconds']+2)
                code=child.returncode
            except subprocess.TimeoutExpired: code='TIMEOUT'
        elapsed=time.perf_counter()-start; later=resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu=later.ru_utime+later.ru_stime-usage.ru_utime-usage.ru_stime
        success=code==0 and (directory/'result.json').exists()
        if success:
            result=json.loads((directory/'result.json').read_text())
            if result['job']!=job or result['context']!=context: raise ValueError('Result identity differs')
            if job['kind']=='duplicate':
                from statistics_tools import paired
                paired(result,result)
        charged_cpu+=child_cpu if success else job['cpu_seconds']; charged_wall+=elapsed if success else max(elapsed,job['wall_seconds'])
        row={'job':job['id'],'success':success,'returncode':code,'cpu_seconds':child_cpu,'wall_seconds':elapsed,
            'result_sha256':digest(directory/'result.json') if success else None}
        rows.append(row); publish(directory/'status.json',row)
        if not success: break
    record={'complete':len(rows)==len(plan['jobs']) and all(r['success'] for r in rows),'cpu_charged_seconds':charged_cpu,
            'wall_charged_seconds':charged_wall,'jobs':rows}
    publish(args.out/'status.json',record); print(json.dumps(record,indent=2))


if __name__=='__main__': main()
