"""Three fixed higher-score WASM pairs; reference inputs were frozen before timing."""
import json
from pathlib import Path
import subprocess

root=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent
node=root/'toolchains/emsdk/node/24.19.0_64bit/bin/node'
checker=root/'TuppiBrowser-speed-port/tests/check_exact_runtime.mjs'
reference=out/'checks/macos-pair-1-baseline.json'
for round_number in (1,2,3):
    for variant in (('baseline','candidate') if round_number%2 else ('candidate','baseline')):
        target=out/f'checks/wasm-pair-{round_number}-{variant}.json'
        if target.exists():raise RuntimeError('Refusing to overwrite an existing job')
        runtime=out/'baseline-wasm/runtime.mjs' if variant=='baseline' else root/'TuppiBrowser-speed-port/web/runtime.mjs'
        subprocess.run([str(node),str(checker),str(runtime),str(reference),str(target)],check=True,timeout=600)
    a=json.loads((out/f'checks/wasm-pair-{round_number}-baseline.json').read_text())
    b=json.loads((out/f'checks/wasm-pair-{round_number}-candidate.json').read_text())
    for key in ['worlds','rules','featureViews','inference','trace']:assert a[key]==b[key],key
    (out/f'checks/wasm-pair-{round_number}-exact.json').write_text(json.dumps({'passed':True,'round':round_number,
        'decisions':len(a['trace']),'scope':'Exact float bits, actions, RNG and full sooli contexts on fixed W1024 inputs'},indent=2)+'\n')
    print(json.dumps({'round':round_number,'passed_exact':True}),flush=True)
