"""One bounded synthetic differential/timing job; writes a reviewable record."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ai',type=Path,required=True)
parser.add_argument('--engine',type=Path,required=True)
parser.add_argument('--exporter',type=Path,required=True)
parser.add_argument('--worlds',type=int,required=True)
parser.add_argument('--scores',default='24,0;40,0')
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
started=time.perf_counter();report={'passed':False,'worlds':args.worlds,'scores':args.scores,
    'exporter_sha256':hashlib.sha256(args.exporter.read_bytes()).hexdigest()}
library=args.ai.resolve()/'native'/('libtuppi.dylib' if sys.platform=='darwin' else 'libtuppi.so')
report['native_sha256']=hashlib.sha256(library.read_bytes()).hexdigest()
try:
    with tempfile.TemporaryDirectory(prefix='tuppi-exact-reference-') as temporary:
        root=Path(temporary);reference=root/'reference.json';timing=root/'timing.json'
        env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1',
            'PYTHONDONTWRITEBYTECODE':'1','TUPPI_NATIVE_LIBRARY':str(library)}
        command=[sys.executable,'-B',str(args.exporter),'--ai',str(args.ai),'--engine',str(args.engine),
            '--worlds',str(args.worlds),'--controller-scores',args.scores,'--trace-options',
            '--timing-output',str(timing),'--out',str(reference)]
        result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=600)
        if result.returncode:raise RuntimeError(result.stderr[-10000:] or result.stdout[-10000:])
        report.update(passed=True,reference=json.loads(reference.read_text()),timing=json.loads(timing.read_text()))
except Exception as error:
    report['error']=str(error)
usage=resource.getrusage(resource.RUSAGE_CHILDREN)
report['resources']={'wall_seconds':time.perf_counter()-started,'child_cpu_seconds':usage.ru_utime+usage.ru_stime,
    'child_peak_rss_bytes':usage.ru_maxrss if sys.platform=='darwin' else usage.ru_maxrss*1024}
report['scope']='Finite exactness/paired timing; no training, strength campaign or device performance claim'
args.out.write_text(json.dumps(report)+'\n')
print(json.dumps({'passed':report['passed'],'worlds':args.worlds,'scores':args.scores,'resources':report['resources']}),file=sys.stderr)
if not report['passed']:sys.exit(1)
