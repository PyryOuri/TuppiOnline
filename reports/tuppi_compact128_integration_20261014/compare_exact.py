"""Compare complete finite references without numerical tolerances."""
import argparse
import json
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline',type=Path);parser.add_argument('candidate',type=Path)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
a=json.loads(args.baseline.read_text());b=json.loads(args.candidate.read_text())
a=a.get('reference',a);b=b.get('reference',b)
def compare(a,b,path=''):
    assert type(a)==type(b),(path,'type differs')
    if isinstance(a,dict):
        assert a.keys()==b.keys(),(path,'fields differ')
        for key in a:compare(a[key],b[key],path+'/'+str(key))
    elif isinstance(a,list):
        assert len(a)==len(b),(path,'length differs')
        for index,(left,right) in enumerate(zip(a,b)):compare(left,right,path+'/'+str(index))
    elif isinstance(a,float):assert a.hex()==b.hex(),(path,a.hex(),b.hex())
    else:assert a==b,(path,repr(a)[:80],repr(b)[:80])
report={'passed':False,'scope':'Complete recursive comparison including exact float hex, actions, RNG and retained option traces'}
try:
    compare(a,b);report.update(passed=True,worlds=a.get('worlds'))
except AssertionError as error:
    report['error']=str(error)
args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if not report['passed']:raise SystemExit(1)
