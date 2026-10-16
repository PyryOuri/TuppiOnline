"""Compare reference and compact128 decision records seed by seed."""
import collections, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
runs = HERE / (sys.argv[1] if len(sys.argv) > 1 else 'runs/games')
seeds = sorted({p.name.split('_')[-1] for p in runs.iterdir() if p.is_dir()})
summary = collections.Counter(); phases = collections.Counter(); cells = set(); contracts = collections.Counter()
detail = []; cpu = {'reference': 0., 'compact128': 0.}; sooli_accepts = 0; gaps = []
for s in seeds:
    try:
        ref = json.loads((runs / f'reference_{s}/result.json').read_text())
        new = json.loads((runs / f'compact128_{s}/result.json').read_text())
    except FileNotFoundError:
        summary['incomplete_seeds'] += 1; continue
    summary['seeds'] += 1; cpu['reference'] += ref['cpu_seconds']; cpu['compact128'] += new['cpu_seconds']
    a, b = [r['exact'] for r in ref['rows']], [r['exact'] for r in new['rows']]
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    same = first is None and len(a) == len(b)
    summary['identical_seeds' if same else 'divergent_seeds'] += 1
    for x in a[:first]:
        summary['decisions_compared'] += 1; phases[x['phase']] += 1
        if x['contract']: contracts[x['contract']] += 1
        if x['values'] and len(x['values']) > 1:
            v = sorted(float.fromhex(h) for h in x['values'].values()); gaps.append(v[-1] - v[-2])
        if x['phase'] == 'SOOLI_GIVE': sooli_accepts += 1
    if not same:
        x, y = a[first], b[first]
        detail.append({'seed': s, 'decision': first, 'label': x['label'], 'phase': x['phase'],
                       'same_action': x['action'] == y['action'], 'same_input': x['input_sha256'] == y['input_sha256'],
                       'fields': [k for k in x if x[k] != y.get(k)],
                       'max_value_diff': max((abs(float.fromhex(x['values'][k]) - float.fromhex(y['values'][k])) for k in x['values']), default=None) if x['values'] and y['values'] else None})
summary['sooli_give_decisions'] = sooli_accepts
gaps.sort()
out = {'summary': dict(summary), 'phases': dict(phases), 'contracts': dict(contracts), 'cpu_seconds': cpu,
       'cpu_reduction': 1 - cpu['compact128'] / cpu['reference'] if cpu['reference'] else None,
       'root_value_gap': {'n': len(gaps), 'min': gaps[0] if gaps else None, 'share_below_1e-4': sum(g < 1e-4 for g in gaps) / max(1, len(gaps)),
                          'share_exact_tie': sum(g == 0 for g in gaps) / max(1, len(gaps))},
       'divergences': detail}
print(json.dumps(out, indent=1))
