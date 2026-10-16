"""Three predeclared, serial, paired fixed-input jobs. Stop on any failure."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent
python='/Users/pyryouri/.venvs/tuppi-v2/bin/python'
helper=root/'TuppiBrowser-speed-port/deploy/run_reference.py'
exporter=root/'TuppiBrowser-speed-port/tests/export_reference.py'
env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1'}
for round_number in (1,2,3):
    order=('baseline','candidate') if round_number%2 else ('candidate','baseline')
    for variant in order:
        ai=root/('TuppiAI-hosted' if variant=='baseline' else 'TuppiAI-speed-port')
        target=out/f'checks/macos-pair-{round_number}-{variant}.json'
        if target.exists():raise RuntimeError('Refusing to overwrite an existing job: '+str(target))
        subprocess.run([python,'-B',str(helper),'--ai',str(ai),'--engine',str(root/'TuppiProject-browser-network'),
            '--exporter',str(exporter),'--worlds','1024','--scores','24,0;40,0','--out',str(target)],env=env,check=True,timeout=620)
        print(json.dumps({'round':round_number,'variant':variant,'complete':True}),flush=True)
    subprocess.run([python,'-B',str(out/'compare_exact.py'),
        str(out/f'checks/macos-pair-{round_number}-baseline.json'),str(out/f'checks/macos-pair-{round_number}-candidate.json'),
        '--out',str(out/f'checks/macos-pair-{round_number}-exact.json')],check=True)
