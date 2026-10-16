"""Three isolated Docker pairs against the retained reference image."""
import json
from pathlib import Path
import subprocess
import uuid

root=Path(__file__).resolve().parents[2];out=Path(__file__).resolve().parent
docker=out/'docker-local'
context='/Users/pyryouri/Developer/deploy/TuppiNetwork-compact128/qualification'
python='/Users/pyryouri/.venvs/tuppi-v2/bin/python'
images={variant:json.loads(subprocess.check_output([str(docker),'image','inspect',tag],text=True))[0]['Id']
    for variant,tag in [('baseline','tuppi-online:qualified'),('candidate','tuppi-online:compact128')]}
(out/'checks/linux-comparison-images.json').write_text(json.dumps(images,indent=2)+'\n')
for round_number in (1,2,3):
    for variant in (('baseline','candidate') if round_number%2 else ('candidate','baseline')):
        target=out/f'checks/linux-pair-{round_number}-{variant}.json'
        if target.exists():raise RuntimeError('Refusing to overwrite an existing job')
        name='tuppi-speed-job-'+uuid.uuid4().hex
        command=[str(docker),'run','--rm','--pull=never','--platform=linux/amd64','--name',name,'--cpus=1','--memory=2g',
            '--mount',f'type=bind,source={context}/export_reference.py,target=/tmp/export_reference.py,readonly',
            '--mount',f'type=bind,source={context}/run_reference.py,target=/tmp/run_reference.py,readonly',
            '--entrypoint','python',images[variant],'-B','/tmp/run_reference.py','--ai','/app/ai','--engine','/app/engine',
            '--exporter','/tmp/export_reference.py','--worlds','1024','--scores','24,0;40,0','--out','/dev/stdout']
        try:
            with target.open('w') as stream:
                subprocess.run(command,stdout=stream,check=True,timeout=620)
        finally:
            subprocess.run([str(docker),'rm','--force',name],capture_output=True,text=True)
        report=json.loads(target.read_text());assert report['passed']
        print(json.dumps({'round':round_number,'variant':variant,'complete':True,'resources':report['resources']}),flush=True)
    subprocess.run([python,'-B',str(out/'compare_exact.py'),
        str(out/f'checks/linux-pair-{round_number}-baseline.json'),str(out/f'checks/linux-pair-{round_number}-candidate.json'),
        '--out',str(out/f'checks/linux-pair-{round_number}-exact.json')],check=True)
