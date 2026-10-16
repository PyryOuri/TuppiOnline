"""Summarise the predeclared finite paired jobs without selecting cases."""
import json
import math
from pathlib import Path
from statistics import median

audit = Path(__file__).resolve().parent


def quantile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


summaries = {}
for backend in ('macos', 'linux', 'wasm'):
    rounds = []
    for number in (1, 2, 3):
        exact = json.loads((audit / f'checks/{backend}-pair-{number}-exact.json').read_text())
        assert exact.get('passed', exact.get('passed_exact', False))
        reports = {name: json.loads((audit / f'checks/{backend}-pair-{number}-{name}.json').read_text())
                   for name in ('baseline', 'candidate')}
        measured = {}
        for name, report in reports.items():
            assert report['passed']
            if backend == 'wasm':
                phases = json.loads((audit / 'checks/macos-pair-1-baseline.json').read_text())['timing']['decisions']
                assert len(phases) == len(report['timings_ms']) == len(report['trace'])
                durations = report['timings_ms']
                bids = [value for value, phase in zip(durations, phases) if phase['phase'] == 'SHOWING']
                cpu = sum(report['cpu_us'].values()) / 1_000_000
                peak = report['peak_rss_kib'] * 1024
            else:
                durations = [d['wall_ns'] / 1_000_000 for d in report['timing']['decisions']]
                bids = [d['wall_ns'] / 1_000_000 for d in report['timing']['decisions'] if d['phase'] == 'SHOWING']
                cpu = report['resources']['child_cpu_seconds']
                peak = report['resources']['child_peak_rss_bytes']
            measured[name] = {'job_cpu_seconds': cpu, 'decision_p95_ms': quantile(durations, .95),
                'bid_p95_ms': quantile(bids, .95), 'peak_rss_bytes': peak, 'decisions': len(durations), 'bids': len(bids)}
        a, b = measured['baseline'], measured['candidate']
        rounds.append({'round': number, 'measurements': measured,
            'cpu_reduction': 1 - b['job_cpu_seconds'] / a['job_cpu_seconds'],
            'decision_p95_ratio': b['decision_p95_ms'] / a['decision_p95_ms'],
            'bid_p95_ratio': b['bid_p95_ms'] / a['bid_p95_ms']})
    summaries[backend] = {'passed_exact': True, 'rounds': rounds,
        'median_paired': {key: median(row[key] for row in rounds)
            for key in ('cpu_reduction', 'decision_p95_ratio', 'bid_p95_ratio')}}
report = {'backends': summaries, 'worlds': 1024, 'scores': [[24, 0], [40, 0]],
    'scope': 'Two fixed synthetic deal inputs, 118 choices/probes and eight bids per job, three paired rounds; includes job setup CPU; no strength, device, native Linux host or population-wide guarantee',
    'linux_execution': 'x86-64 OpenBLAS in a one-CPU ARM64 Lima VM through Rosetta',
    'quantiles': 'Linear interpolation between adjacent ordered decision durations'}
(audit / 'checks/TIMING_SUMMARY.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({name: value['median_paired'] for name, value in summaries.items()}, indent=2))
