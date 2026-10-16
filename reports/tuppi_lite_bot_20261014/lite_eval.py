"""Duplicate evaluation through tuppi_ai.evaluate with the Lite factories (PLAN.md).

    python lite_eval.py --candidate L0 --opponent live128 --seed lite-screen-v1|L0 --first 0 --deals 512 --out results/x.json
"""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lite_agents import TUPPIAI, make  # noqa: E402,F401


def _init(candidate: str, opponent: str) -> None:
    import torch
    torch.set_num_threads(1)
    from tuppi_ai import evaluate as ev, native
    from tuppi_ai.equity import Equity
    native.set_rollout_chunk(128)  # as tuppi_ai.evaluate: several processes, same moves
    ev._W['equity'] = Equity.load(TUPPIAI / 'models' / 'equity_incumbent.json')
    ev._W['ruleset'] = 'v3'
    ev._W['opponent'] = ev._with_sooli(make(opponent), 'v3')
    ev._W['candidate'] = ev._with_sooli(make(candidate), 'v3')


def _measure(index: int, seed: str) -> dict:
    from tuppi_ai import evaluate as ev
    row = ev.measure(index, seed, 'uniform')
    row['cpu_seconds_worker_total'] = time.process_time()
    return row


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--candidate', required=True); p.add_argument('--opponent', required=True)
    p.add_argument('--seed', required=True); p.add_argument('--first', type=int, default=0)
    p.add_argument('--deals', type=int, required=True); p.add_argument('--workers', type=int, default=12)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise SystemExit(f'{a.out} exists; results are never overwritten')
    t0 = time.time()
    idx = list(range(a.first, a.first + a.deals))
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.candidate, a.opponent)) as pool:
        rows = list(pool.map(_measure, idx, [a.seed] * len(idx), chunksize=4))
    from tuppi_ai import evaluate as ev
    summary = ev.summarise(rows)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    summary.update({'candidate': a.candidate, 'opponent': a.opponent, 'seed': a.seed, 'first': a.first,
                    'scores': 'uniform', 'ruleset': 'project_target_v3', 'wall_seconds': round(time.time() - t0, 1),
                    'child_cpu_seconds': children.ru_utime + children.ru_stime,
                    'indices': [r['index'] for r in rows], 'values': [r['value'] for r in rows],
                    'deal_scores': [r['score'] for r in rows], 'games': [g for r in rows for g in r['games']]})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open('x') as f:
        json.dump(summary, f, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('values', 'games', 'indices', 'deal_scores')}, indent=1))


if __name__ == '__main__':
    main()
