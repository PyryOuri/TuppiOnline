"""Broad W1024 differential: fresh seeds, both variants, through the qualified worker.

Each job is one seed: two deals with controllers retained, score cell drawn
by the seed. Jobs run as independent single-thread processes; timings are
not measured here, only exact decision records.
"""
import argparse, concurrent.futures as cf, json, os, subprocess
from pathlib import Path
HERE = Path(__file__).resolve().parent
QUAL = HERE.parent / 'tuppi_speed_qualification_20261014'
PYTHON = '/Users/pyryouri/.venvs/tuppi-v2/bin/python'


def one(job, dest):
    folder = dest / job['id']; folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'result.json').exists(): return job['id'], 0
    (folder / 'job.json').write_text(json.dumps(job))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
    for k in ('PYTHONPATH', 'TUPPI_CHEAP_WINS_LIBRARY', 'TUPPI_AI_SERIAL'): env.pop(k, None)
    with (folder / 'worker.log').open('w') as log:
        code = subprocess.run([PYTHON, '-B', str(QUAL / 'worker.py'), '--job', str(folder / 'job.json'), '--out', str(folder / 'result.json')],
                              env=env, stdout=log, stderr=subprocess.STDOUT, timeout=job['wall_seconds'] + 30).returncode
    return job['id'], code


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--seeds', type=int, default=100); ap.add_argument('--first', type=int, default=0)
    ap.add_argument('--samples', type=int, default=2); ap.add_argument('--workers', type=int, default=12)
    ap.add_argument('--out', type=Path, default=HERE / 'runs/games'); a = ap.parse_args()
    jobs = [{'id': f'{v}_{i:03d}', 'mode': 'games', 'variant': v, 'worlds': 1024, 'parallel': False,
             'seed': f'speed-differential-{i}', 'samples': a.samples, 'cpu_seconds': 900, 'wall_seconds': 1800}
            for i in range(a.first, a.first + a.seeds) for v in ('reference', 'compact128')]
    with cf.ThreadPoolExecutor(a.workers) as pool:
        for jid, code in pool.map(lambda j: one(j, a.out), jobs): print(jid, code, flush=True)


if __name__ == '__main__': main()
