"""Summarize technical timing repeats and apply the recorded engineering gates."""
import json
import math
from pathlib import Path
import statistics

OUT=Path(__file__).resolve().parent
VARIANTS=['reference','combo32','combo128','compact128']


def quantile(values,q=0.95):
    if not values: raise ValueError('Empty timing sample')
    ordered=sorted(values); location=(len(ordered)-1)*q
    low=math.floor(location); fraction=location-low
    return ordered[low]*(1-fraction)+ordered[min(low+1,len(ordered)-1)]*fraction


def main():
    gates=json.loads((OUT/'GATES.json').read_text())
    if json.loads((OUT/'FACTORY_CHECK.json').read_text())['status']!='PASS': raise ValueError('Factory check missing')
    for stage in ('parity','timing','parallel','parallel_parity'):
        status=json.loads((OUT/'runs'/stage/'status.json').read_text())
        if not status['complete'] or not status['all_exact']: raise ValueError('Qualification not complete: '+stage)
    if json.loads((OUT/'PARALLEL_CROSS_CHECK.json').read_text())['status']!='PASS': raise ValueError('Serial/parallel corpus mismatch')
    records={stage:{} for stage in ('timing','parallel')}
    for stage in records:
        for variant in VARIANTS:
            samples=[]
            for index in range(1,6):
                folder=OUT/'runs'/stage/f'r{index}_{variant}'
                result=json.loads((folder/'result.json').read_text()); status=json.loads((folder/'status.json').read_text())
                rows=result['rows']; decision_cpu=sum(r['cpu_seconds'] for r in rows)
                sample={'round':index,'child_cpu_seconds':status['child_cpu_seconds'],'worker_wall_seconds':result['seconds'],
                    'decision_cpu_seconds':decision_cpu,'construction_cpu_seconds':result['construction']['cpu_seconds'],
                    'p95_decision_seconds':quantile([r['seconds'] for r in rows]),
                    'p95_bid_seconds':quantile([r['seconds'] for r in rows if r['exact']['phase']=='SHOWING']),
                    'peak_rss_bytes_macos':result['peak_rss_bytes_macos'],'exact_sha256':result['exact_sha256']}
                samples.append(sample)
            records[stage][variant]=samples
    # Every timing replicate is the same two fixed trajectories. Check across
    # rounds and dispatch modes, not just against one paired job in each round.
    identities={row['exact_sha256'] for stage in records.values() for samples in stage.values() for row in samples}
    if len(identities)!=1: raise ValueError('Across-round/dispatch trace mismatch')
    observations={}
    for variant in VARIANTS:
        ratios=[c['child_cpu_seconds']/r['child_cpu_seconds'] for c,r in zip(records['timing'][variant],records['timing']['reference'])]
        latencies=[c['p95_decision_seconds']/r['p95_decision_seconds'] for c,r in zip(records['parallel'][variant],records['parallel']['reference'])]
        bids=[c['p95_bid_seconds']/r['p95_bid_seconds'] for c,r in zip(records['parallel'][variant],records['parallel']['reference'])]
        observations[variant]={'median_serial_cpu_seconds':statistics.median(r['child_cpu_seconds'] for r in records['timing'][variant]),
            'paired_serial_cpu_reductions':[1-x for x in ratios],'median_serial_cpu_reduction':1-statistics.median(ratios),
            'median_parallel_p95_ratio':statistics.median(latencies),'median_parallel_bid_p95_ratio':statistics.median(bids),
            'median_parallel_wall_seconds':statistics.median(r['worker_wall_seconds'] for r in records['parallel'][variant]),
            'median_parallel_peak_rss_bytes_macos':statistics.median(r['peak_rss_bytes_macos'] for r in records['parallel'][variant])}
    selected='reference'; selection=[]
    for variant in gates['order']:
        obs=observations[variant]
        incremental=[1-c['child_cpu_seconds']/r['child_cpu_seconds'] for c,r in zip(records['timing'][variant],records['timing'][selected])]
        latency=[c['p95_decision_seconds']/r['p95_decision_seconds'] for c,r in zip(records['parallel'][variant],records['parallel'][selected])]
        bids=[c['p95_bid_seconds']/r['p95_bid_seconds'] for c,r in zip(records['parallel'][variant],records['parallel'][selected])]
        gain=statistics.median(incremental)
        passed=(obs['median_serial_cpu_reduction']>=gates['overall_median_serial_cpu_reduction_min']
            and (selected=='reference' or gain>=gates['incremental_median_serial_cpu_reduction_min'])
            and obs['median_parallel_p95_ratio']<=gates['native_parallel_p95_ratio_max']
            and obs['median_parallel_bid_p95_ratio']<=gates['native_parallel_bid_p95_ratio_max']
            and statistics.median(latency)<=gates['native_parallel_p95_ratio_max']
            and statistics.median(bids)<=gates['native_parallel_bid_p95_ratio_max'])
        selection.append({'variant':variant,'compared_with':selected,'incremental_median_serial_cpu_reduction':gain,
            'incremental_parallel_p95_ratio':statistics.median(latency),'incremental_parallel_bid_p95_ratio':statistics.median(bids),'passes':passed})
        if passed: selected=variant
    result={'schema':'tuppi.speed_qualification.summary.v1','all_qualified_traces_exact':True,'unique_natural_deals':2,
        'technical_rounds_per_mode':5,'complete_deal_executions_per_mode':40,'observations':observations,
        'selected_variant':selected,'selection':selection,'records':records,
        'qualification':'Five technical repetitions of the same two retained W1024 deals. Paired CPU/latency observations, without independent-deal generalization, app/device acceptance or strength evidence.'}
    with (OUT/'SUMMARY.json').open('x') as f: json.dump(result,f,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))


if __name__=='__main__': main()
