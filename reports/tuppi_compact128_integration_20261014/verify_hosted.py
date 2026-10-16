"""Verify the approved private release. Read temporary auth only from stdin."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import difflib
import json
from pathlib import Path
import sys
import ssl
import termios
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.parse import urlsplit
from zipfile import ZipFile

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme=='https' and urlsplit(newurl).netloc==urlsplit(base).netloc:
            return super().redirect_request(req,fp,code,msg,headers,newurl)
        raise RuntimeError('Private Site redirected outside its own origin')

if sys.stdin.isatty():
    attrs=termios.tcgetattr(sys.stdin);attrs[3]&=~termios.ECHO;termios.tcsetattr(sys.stdin,termios.TCSANOW,attrs)
print('Ready for private verification JSON on stdin (input is hidden).',flush=True)
settings=json.loads(sys.stdin.readline())
base='https://tuppi-offline-202b74f.sos-health-p-7158.chatgpt.site'
root=Path(__file__).resolve().parent
with ZipFile(root/settings.get('archive','offline-hosted-release.zip')) as archive:
    expected={name:archive.read(name) for name in archive.namelist()}

def verify(item):
    name,body=item
    request=Request(base+'/'+name,headers={'OAI-Sites-Authorization':'Bearer '+settings['token']})
    with build_opener(NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile='/etc/ssl/cert.pem'))).open(request,timeout=30) as response:
        actual=response.read()
        record={'path':name,'bytes':len(actual),'expected_bytes':len(body),'sha256':hashlib.sha256(actual).hexdigest(),
            'exact':response.status==200 and actual==body,'content_type':response.headers.get_content_type()}
        if name.endswith('.html') and not record['exact']:
            diff=difflib.SequenceMatcher(None,body,actual,autojunk=False)
            record['html_diagnostic']={'expected_title_present':b'<title>Tuppi</title>' in actual,
                'expected_table_present':'Tuppipöytä'.encode() in actual,'similarity':diff.ratio(),
                'changes':[(tag,a2-a1,b2-b1) for tag,a1,a2,b1,b2 in diff.get_opcodes() if tag!='equal']}
        return record

with ThreadPoolExecutor(max_workers=4) as pool:
    verified=list(pool.map(verify,expected.items()))
for asset in verified:
    if asset['path'].endswith('.mjs'):
        assert asset['content_type'] in ('text/javascript','application/javascript'), 'JavaScript MIME is invalid'
    if asset['path'].endswith('.wasm'):
        assert asset['content_type']=='application/wasm', 'WASM MIME is invalid'
records={r['path']:r for r in verified}
manifest=json.loads(expected['offline-manifest.json'])
for asset in verified:
    if asset['path'].endswith('.html') and not asset['exact']:
        source=next((r.get('source_path') for r in manifest['files'] if r['path']==asset['path']),None)
        changes=asset.get('html_diagnostic',{}).get('changes',[])
        asset['verified_shell']=bool(source and records.get(source,{}).get('exact') and changes and all(c[0]=='insert' for c in changes))
report={'passed':all(r['exact'] or r.get('verified_shell') for r in verified),'url':base,'files':len(verified),'bytes':sum(r['bytes'] for r in verified),
    'checks':['authenticated HTTPS retrieval','exact asset and plain-text shell comparison; document decoration recorded'],
    'assets':verified,'scope':'HTTP bytes; browser authentication, service workers and iPhone acceptance remain pending'}
(root/'HOSTED_HTTP_CHECKS.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='assets'}))
print(json.dumps({'mismatched':[r for r in verified if not r['exact']]}))
