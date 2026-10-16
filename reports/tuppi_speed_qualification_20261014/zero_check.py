"""Additional natural W1024 parity at 0-0, selected solely by its score cell."""
import json
import random
from run import OUT,digest,execute,publish


def main():
    # Choose before execution by score, never by a controller's outcome/cost.
    for index in range(1000):
        seed=f'speed-zero-start-{index}'
        if random.Random(f'{seed}|score|0').randrange(25)==0: break
    else: raise RuntimeError('No zero-score seed in finite search')
    variant=json.loads((OUT/'QUALIFIED_BASELINE.json').read_text())['variant']
    plan=json.loads((OUT/'PLAN.json').read_text())
    stages={}
    for stage,parallel,cpu,wall in [('zero_serial',False,90,120),('zero_parallel',True,150,180)]:
        stages[stage]=[{'id':name,'mode':'games','variant':name,'worlds':1024,'parallel':parallel,'seed':seed,'samples':1,
                        'cpu_seconds':cpu,'wall_seconds':wall} for name in ['reference',variant]]
    extra={'schema':'tuppi.speed_qualification.zero_plan.v1','seed':seed,'score':[0,0],'selection':'First finite seed whose designated score cell is 0, without outcome/cost screening','stages':stages}
    publish(OUT/'ZERO_PLAN.json',extra)
    plan['inputs']['ZERO_PLAN.json']=digest(OUT/'ZERO_PLAN.json')
    for stage,jobs in stages.items():
        plan['stages'][stage]=jobs; plan['budgets'][stage]={'cpu_seconds':sum(j['cpu_seconds'] for j in jobs),'wall_seconds':sum(j['wall_seconds'] for j in jobs)}
        execute(stage,plan)
    values=[json.loads((OUT/'runs'/stage/name/'result.json').read_text()) for stage in stages for name in ['reference',variant]]
    passed=len({r['exact_sha256'] for r in values})==1
    publish(OUT/'ZERO_CHECK.json',{'status':'PASS' if passed else 'FAIL','unique_extra_deals':1,'score':[0,0],'selected_variant':variant,
        'serial_and_parallel_exact':passed,'qualification':'One extra natural 0-0 deal for parity, not a repeated speed estimate.'})
    if not passed: raise SystemExit(1)


if __name__=='__main__': main()
