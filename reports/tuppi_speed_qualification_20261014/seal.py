"""Seal completed qualification evidence and the prepared analysis entry points."""
import hashlib
import json
from pathlib import Path
from run import OUT,PREP,verify,publish


def main():
    plan=json.loads((OUT/'PLAN.json').read_text()); verify(plan)
    for stage in ('parity','timing','parallel','parallel_parity','zero_serial','zero_parallel'):
        record=json.loads((OUT/'runs'/stage/'status.json').read_text())
        if not record['complete'] or not record['all_exact']: raise ValueError('Incomplete qualification: '+stage)
    for name in ('FACTORY_CHECK.json','WRAPPER_CHECK.json','ZERO_CHECK.json','PARALLEL_CROSS_CHECK.json'):
        if json.loads((OUT/name).read_text())['status']!='PASS': raise ValueError('Check failed: '+name)
    summary=json.loads((OUT/'SUMMARY.json').read_text()); baseline=json.loads((OUT/'QUALIFIED_BASELINE.json').read_text())
    if summary['selected_variant']!=baseline['variant']: raise ValueError('Selected baseline differs')
    import sys
    sys.path.insert(0,str(PREP))
    from launch import validate_plan
    previews={path.name:validate_plan(json.loads(path.read_text())) for path in (OUT/'configs').glob('*.json')}
    # No qualifier, costing plan, library or evidence is overwritten by sealing.
    files=[p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in {'PACKAGE.json','VALIDATION.json'}
           and not p.is_relative_to(OUT/'analysis_runs')]
    record={'schema':'tuppi.speed_qualification.package.v1','base_package_sha256':plan['base_package_sha256'],
        'selected_variant':baseline['variant'],'files':{str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        'scope':'Qualified exact-on-checked-corpus common implementation and prepared costing plans. No strength campaign or live deployment.',
        'prepared_plan_previews':previews}
    publish(OUT/'PACKAGE.json',record)
    print(json.dumps({'files':len(files),'selected_variant':baseline['variant'],'package_sha256':hashlib.sha256((OUT/'PACKAGE.json').read_bytes()).hexdigest()},indent=2))


if __name__=='__main__': main()
