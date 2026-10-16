"""Explicit finite follow-up: forced-row compaction and two more batch pairs."""
import json
import statistics
from pathlib import Path
from probe import OUT, run


def fingerprints(result): return [row['fingerprint'] for row in result['rows']]


def main():
    gold=json.loads((OUT/'checks_v2/roots_installed.json').read_text())
    projection=lambda result:[{k:v for k,v in row.items() if k!='wall_seconds'} for row in result['rows']]
    roots={variant:run('roots',variant) for variant in ('same_net_only','compact_rows')}
    root_parity={name:projection(value)==projection(gold) for name,value in roots.items()}
    assert all(root_parity.values()),root_parity
    base=run('game','same_net_only')
    compact=run('game','compact_rows')
    assert fingerprints(compact)==fingerprints(base)
    initial_base=json.loads((OUT/'checks_v2/game_reference.json').read_text())
    initial_chunk=json.loads((OUT/'checks_v2/game_chunk128.json').read_text())
    paired=[{'order':['reference','chunk128'],'cpu_base':initial_base['cpu_seconds'],'cpu_chunk128':initial_chunk['cpu_seconds']}]
    for index,order in enumerate((('chunk128','reference'),('reference','chunk128')),start=2):
        rows={variant:run('game',variant,suffix=f'_repeat{index}') for variant in order}
        assert fingerprints(rows['reference'])==fingerprints(initial_base)==fingerprints(rows['chunk128'])
        paired.append({'order':list(order),'cpu_base':rows['reference']['cpu_seconds'],'cpu_chunk128':rows['chunk128']['cpu_seconds']})
    compact1024=run('game','compact_rows',worlds=1024,samples=1,suffix='_W1024')
    baseline1024=json.loads((OUT.parent/'tuppi_cheap_wins_preparation_20261014/checks/w1024_qualification/same_net_result.json').read_text())
    assert fingerprints(compact1024)==fingerprints(baseline1024)
    record={'schema':'tuppi.additional_exact_wins.followup.v1','compact_root_parity':root_parity,
            'compact_W128_trace_parity':True,'compact_W1024_trace_parity':True,
            'compact_W128_cpu_seconds':compact['cpu_seconds'],'same_net_W128_cpu_seconds':base['cpu_seconds'],
            'compact_W128_incremental_cpu_reduction':1-compact['cpu_seconds']/base['cpu_seconds'],
            'compact_W128_mlp_rows':compact['mlp_metrics'][1],'same_net_W128_mlp_rows':base['mlp_metrics'][1],
            'batch_size_pairs':paired,'batch128_median_cpu_reduction':statistics.median(1-row['cpu_chunk128']/row['cpu_base'] for row in paired),
            'qualification':'Three short W128 timing pairs for chunk128. One compacted W128 pair and one W1024 trace qualification; W1024 timing is not paired here. No strength result.'}
    with (OUT/'FOLLOWUP.json').open('x') as f: json.dump(record,f,indent=2)
    print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__': main()
