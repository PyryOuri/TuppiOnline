"""Later analysis jobs with the selected speed settings on every searched arm."""
import argparse
import importlib.util
import json
from pathlib import Path
import resource
import signal
import sys
import time

from bindings import OUT,PREP,activate,agents


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--job',type=Path,required=True); parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); envelope=json.loads(args.job.read_text()); job,context=envelope['job'],envelope['context']
    baseline=json.loads((OUT/'QUALIFIED_BASELINE.json').read_text())
    variant=baseline['variant']
    resource.setrlimit(resource.RLIMIT_CPU,(job['cpu_seconds'],job['cpu_seconds'])); signal.alarm(job['wall_seconds'])
    start,cpu=time.perf_counter(),time.process_time()
    candidates,native,best=activate(variant,parallel=not job['serial'])
    if variant!='reference':
        candidates.agents=lambda arm,worlds=1024,seed=0,seats=range(4): agents(candidates,native,best,variant,worlds,seed,seats,arm)
    spec=importlib.util.spec_from_file_location('frozen_analysis_worker',PREP/'worker.py')
    worker=importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    result={'duplicate':worker.duplicate,'match_cost':worker.match_cost}[job['kind']](job,context)
    import torch,numpy as np
    result.update(seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,job=job,
        peak_rss_bytes_macos=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        dependency_versions={'torch':torch.__version__,'numpy':np.__version__,'python':sys.version,'executable':sys.executable})
    if job['kind']=='duplicate':
        from statistics_tools import paired
        paired(result,result)
    with args.out.open('x') as f: json.dump(result,f,indent=2,allow_nan=False); f.write('\n')
    signal.alarm(0)


if __name__=='__main__': main()
