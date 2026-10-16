"""Decision statistics for PLAN.md gates.

    python analyse.py head results/strength/a.json [b.json ...]   # pooled head-to-head (candidate - opponent)
    python analyse.py guard results/strength/guard.json            # paired with the stored live-W128 guard run
"""
import json, math, statistics, sys
from pathlib import Path

P1B = Path('/Users/pyryouri/Developer/TuppiAI/runs/panel/P1b-A__heur__cand.json')


def ci(values):
    m = statistics.fmean(values); se = statistics.stdev(values) / math.sqrt(len(values))
    return {'n': len(values), 'mean': m, 'se': se, 'lo': m - 1.96 * se, 'hi': m + 1.96 * se}


def rates(games):
    n = len(games)
    return {k: sum(float(g[k]) for g in games) / n for k in ('cand_declared', 'opp_declared', 'stolen', 'cand_sooli', 'opp_sooli', 'won')}


def head(paths):
    rs = [json.loads(Path(p).read_text()) for p in paths]
    idx = [i for r in rs for i in r['indices']]
    assert len(idx) == len(set(idx)), 'overlapping base deals'
    assert len({(r['candidate'], r['opponent'], r['seed']) for r in rs}) == 1, 'incompatible runs'
    out = ci([v for r in rs for v in r['values']])
    out.update(candidate=rs[0]['candidate'], opponent=rs[0]['opponent'], seed=rs[0]['seed'],
               rates=rates([g for r in rs for g in r['games']]), wall_seconds=sum(r['wall_seconds'] for r in rs),
               child_cpu_seconds=sum(r['child_cpu_seconds'] for r in rs))
    return out


def guard(path):
    r = json.loads(Path(path).read_text()); ref = json.loads(P1B.read_text())
    assert r['seed'] == ref['seed'] and r['opponent'] == 'profile:partner_aware_lead_v3'
    refv = ref['values']
    diffs = [v - refv[i] for i, v in zip(r['indices'], r['values'])]
    out = ci(diffs)
    out.update(candidate_vs_heur=ci(r['values']), live128_vs_heur=ci([refv[i] for i in r['indices']]),
               rates=rates(r['games']))
    return out


if __name__ == '__main__':
    mode, *paths = sys.argv[1:]
    print(json.dumps(head(paths) if mode == 'head' else guard(paths[0]), indent=1))
