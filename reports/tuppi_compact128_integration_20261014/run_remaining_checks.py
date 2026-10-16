"""Finish the fixed qualification plan serially, after the Linux paired jobs."""
from pathlib import Path
import subprocess
import sys

audit = Path(__file__).resolve().parent
root = audit.parents[1]
node = root / 'toolchains/emsdk/node/24.19.0_64bit/bin/node'
jobs = [
    ('image-game', [str(node), str(root / 'TuppiBrowser-speed-port/tests/check_hosted_image.mjs'),
        '--docker=' + str(audit / 'docker-local'), '--image=tuppi-online:compact128',
        '--report=' + str(audit / 'checks/linux-image-game.json')], 1100),
    ('wasm-pairs', [sys.executable, '-B', str(audit / 'run_wasm_pairs.py')], 3700),
    ('release-regressions', [sys.executable, '-B', str(audit / 'run_release_regressions.py')], 700),
]
for label, command, cap in jobs:
    print('Starting ' + label, flush=True)
    log = audit / 'checks' / (label + '.log')
    if log.exists():
        raise RuntimeError('Refusing to overwrite existing job log: ' + str(log))
    process = subprocess.Popen(command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with log.open('w') as stream:
            # Each child also has its own bounded subprocess or functional deadline.
            for line in process.stdout:
                stream.write(line); stream.flush(); print(line, end='', flush=True)
        code = process.wait(timeout=cap)
        if code:
            raise subprocess.CalledProcessError(code, command)
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=30)
    print('Completed ' + label, flush=True)
