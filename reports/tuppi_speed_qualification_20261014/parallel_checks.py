"""Qualify the full fixed corpus under native dispatch and against serial traces."""
import json
from run import OUT,digest,execute,publish


def main():
    plan=json.loads((OUT/'PLAN.json').read_text())
    extra=json.loads((OUT/'PARALLEL_PARITY_PLAN.json').read_text())
    if digest(OUT/'PLAN.json')!=extra['base_plan_sha256']: raise ValueError('Base plan changed')
    plan['inputs']['PARALLEL_PARITY_PLAN.json']=digest(OUT/'PARALLEL_PARITY_PLAN.json')
    plan['stages']['parallel_parity']=extra['jobs']
    plan['budgets']['parallel_parity']={'cpu_seconds':extra['budget_cpu_seconds'],'wall_seconds':extra['budget_wall_seconds']}
    execute('parallel_parity',plan)
    comparisons=[]
    for job in extra['jobs']:
        parallel=json.loads((OUT/'runs/parallel_parity'/job['id']/'result.json').read_text())
        serial=json.loads((OUT/'runs/parity'/f'{job["mode"]}_{job["variant"]}'/'result.json').read_text())
        comparisons.append({'job':job['id'],'same_runtime':parallel['dependency_versions']==serial['dependency_versions'],
            'exact_equal_to_serial':parallel['exact_sha256']==serial['exact_sha256'] and len(parallel['rows'])==len(serial['rows'])})
    passed=all(r['same_runtime'] and r['exact_equal_to_serial'] for r in comparisons)
    publish(OUT/'PARALLEL_CROSS_CHECK.json',{'status':'PASS' if passed else 'FAIL','comparisons':comparisons})
    if not passed: raise SystemExit(1)
    print('All native-parallel corpus traces also match the serial traces.',flush=True)


if __name__=='__main__': main()
