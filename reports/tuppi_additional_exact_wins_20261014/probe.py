"""Finite one-worker probe programme, no strength comparisons or production writes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
PREP = OUT.parent/'tuppi_cheap_wins_preparation_20261014'
PYTHON = '/Users/pyryouri/.venvs/tuppi-v2/bin/python'


def run(mode, variant, *, worlds=128, samples=2, suffix=''):
    directory = OUT/'checks_v2'; directory.mkdir(exist_ok=True)
    stem = f'{mode}_{variant}{suffix}'
    env = dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
    env.pop('PYTHONPATH',None)
    lib = PREP/'frozen/ai/native/libtuppi.dylib' if variant=='installed' else OUT/'builds'/('reference' if variant in ('chunk128','same_net_only') else variant)/'libtuppi.dylib'
    env['TUPPI_CHEAP_WINS_LIBRARY']=str(lib)
    command=[PYTHON,'-B',str(OUT/'probe_one.py'),'--mode',mode,'--variant',variant,'--worlds',str(worlds),'--samples',str(samples),'--out',str(directory/(stem+'.json'))]
    print('starting',stem,flush=True)
    with (directory/(stem+'.log')).open('x') as log:
        result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=92)
    if result.returncode:
        print((directory/(stem+'.log')).read_text()[-4000:],flush=True)
        raise RuntimeError(f'Failed {stem}: {result.returncode}; no automatic retry')
    value=json.loads((directory/(stem+'.json')).read_text())
    print('passed',stem,'cpu',round(value['cpu_seconds'],3),flush=True)
    return value


def main():
    sys.path.insert(0,str(PREP))
    from launch import verify
    verify()
    before=time.perf_counter()
    variants=['reference','forced_rows','scratch','chunk128','combined_speed']
    reference=run('roots','installed')
    projection=lambda value:[{k:v for k,v in row.items() if k!='wall_seconds'} for row in value['rows']]
    record={'schema':'tuppi.additional_exact_wins.probes.v1','native_root_parity':{},'mlp_parity':{},'game_parity':{},'timing_observations':{}}
    for variant in variants:
        result=run('roots',variant)
        record['native_root_parity'][variant]=projection(result)==projection(reference)
        assert record['native_root_parity'][variant],variant
    mlp=run('mlp','installed')
    for variant in ('reference','scratch'):
        result=run('mlp',variant)
        record['mlp_parity'][variant]=result['hashes']==mlp['hashes']
        assert record['mlp_parity'][variant],variant
    games={}
    for variant in variants:
        games[variant]=run('game',variant)
        if variant=='reference': continue
        record['game_parity'][variant]=[r['fingerprint'] for r in games[variant]['rows']]==[r['fingerprint'] for r in games['reference']['rows']]
        assert record['game_parity'][variant],variant
    for variant,result in games.items():
        counts=result['rollout_metrics']
        record['timing_observations'][variant]={'worlds':128,'deals':2,'cpu_seconds':result['cpu_seconds'],'wall_seconds':result['wall_seconds'],
            'cpu_reduction_vs_reference':1-result['cpu_seconds']/games['reference']['cpu_seconds'],
            'rollout_rows':counts[0],'forced_rows':counts[1],'all_forced_chunk_rows':counts[2],
            'mlp_calls':result['mlp_metrics'][0],'mlp_rows':result['mlp_metrics'][1],'scratch_grows':result['mlp_metrics'][2]}
    record['wall_seconds']=time.perf_counter()-before
    record['prior_harness_failure']='checks/roots_installed.log: double snapshot activation before gameplay, corrected in this explicit second attempt'
    record['qualification']='Exact only on checked inputs. Two retained W128 deals, one execution per variant; cost observations include process startup, not strength evidence or repeated speed estimates.'
    with (OUT/'PROBES.json').open('x') as f: json.dump(record,f,indent=2)
    print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__': main()
