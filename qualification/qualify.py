"""Fail the Linux image build unless its frozen controller comparisons pass."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'engine/src'),str(root/'ai')]
from tuppi_server.hosted import verify_bot_identity

def compare(expected,actual,path='',tolerance=1e-8):
    if type(expected) is dict:
        if type(actual) is not dict or expected.keys()!=actual.keys(): raise AssertionError(path+' fields differ')
        for key in expected: compare(expected[key],actual[key],path+'/'+str(key),tolerance)
    elif type(expected) is list:
        if type(actual) is not list or len(expected)!=len(actual): raise AssertionError(path+' length differs')
        for index,(a,b) in enumerate(zip(expected,actual)): compare(a,b,path+'/'+str(index),tolerance)
    elif type(expected) is float:
        limit=1e-4 if path.startswith('/inference/models/') else tolerance
        if not isinstance(actual,(int,float)) or not math.isfinite(actual) or abs(expected-actual)>limit:
            raise AssertionError(path+' numeric value differs')
    elif expected!=actual: raise AssertionError(path+' value differs')

identity=verify_bot_identity(os.environ.get('TUPPI_HOSTED_BOT_LEVEL','full'))
reports=[]
for worlds in (128,1024):
    expected_path=root/f'qualification/reference-w{worlds}.json'
    expected=json.loads(expected_path.read_text())
    with tempfile.TemporaryDirectory() as temporary:
        output=Path(temporary)/'reference.json'
        subprocess.run([sys.executable,str(root/'qualification/export_reference.py'),
            '--ai',str(root/'ai'),'--engine',str(root/'engine'),'--out',str(output),'--worlds',str(worlds)],check=True,timeout=600)
        compare(expected,json.loads(output.read_text()))
    reports.append({'worlds':worlds,'passed':True,'reference_sha256':hashlib.sha256(expected_path.read_bytes()).hexdigest()})
report={'passed':True,'platform':sys.platform,'bot':identity,'references':reports,
    'scope':'Synthetic engine, feature, model, controller and forced-sooli qualification; not a strength or capacity benchmark'}
(root/'qualification/result.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
