"""Package and validate static audit deliverables; no game imports or execution."""
from pathlib import Path
import ast, hashlib, json, re, subprocess, zipfile
O=Path(__file__).resolve().parent; R=O.parent.parent
sha=lambda b:hashlib.sha256(b).hexdigest()
repos=json.loads((O/'pre_state.json').read_text()); ev=json.loads((O/'evidence.json').read_text())
byid={e['evidence_id']:e for e in ev}
def clean(s):
 s=re.sub(r'/Users/[^/\s]+','<LOCAL_HOME>',s)
 return re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}','<REDACTED_EMAIL>',s)
def source(e): return R/repos[e['repo']]['path']/e['path']
post={}
for a,v in repos.items():
 def git(*args): return subprocess.check_output(['git','--no-optional-locks','-C',str(R/v['path']),*args],text=True).strip()
 post[a]={'head':git('rev-parse','HEAD'),'branch':git('branch','--show-current'),'status':git('status','--short'),'diff_stat':git('diff','--stat')}
for a,v in repos.items():
 assert all(post[a][k]==v[k] for k in post[a]),f'Working tree changed: {a}'
changed=[e['evidence_id'] for e in ev if sha(source(e).read_bytes())!=e['sha256']]
assert not changed,changed
(O/'post_state.json').write_text(json.dumps(post,indent=2)+'\n')
# Decisive dependency source, no data files or historical banks.
dep_ids=['E011','E015','E018','E022','E023','E024','E025','E026','E027','E028','E029','E030','E031','E032','E033','E034','E035','E036','E039','E050','E052','E055','E056','E057','E059','E060','E061']
parts=['STATIC AUDIT DEPENDENCY CAPSULES\nOriginal source hashes/ranges are in evidence.json. No code here was executed. Personal paths, if present, are redacted. This supplement is source evidence, not a candidate implementation.\n']
for id in dep_ids:
 e=byid[id];parts.append(f'\n=== {id} | {e["repo"]} | {e["path"]} | complete selected dependency ===\n'+clean(source(e).read_text()))
# Only the persistence reconstruction method, not unrelated UI/server implementation.
e=byid['E020'];s=source(e).read_text();t=ast.parse(s)
n=next(n for n in ast.walk(t) if isinstance(n,ast.FunctionDef) and n.name=='from_persistence_record')
parts.append(f'\n=== E020 | LiveMatchRunner.from_persistence_record | {n.lineno}-{n.end_lineno} ===\n'+clean('\n'.join(s.splitlines()[n.lineno-2:n.end_lineno])))
(O/'DEPENDENCY_SOURCE_CAPSULES.txt').write_text('\n'.join(parts))
analysis=(O/'analysis.md').read_text(); closing=(O/'closing.md').read_text()
closing=closing.replace('The packaging scripts in this bundle use','The packaging scripts in the audit output directory use')
manifest=['\n### Current evidence inventory\n\nID | Repo | Relative path | Symbol/range scope | SHA-256 | Type / execution\n---|---|---|---|---|---\n']
for e in ev:
 manifest.append(f'{e["evidence_id"]} | {e["repo"]} | `{e["path"]}` | file lines1–{e["lines"][1]}; exact symbol ranges in index/capsules | `{e["sha256"]}` | {e["type"]}'+(' / NOT RUN' if e['type']=='TEST' else '')+'\n')
manifest.append('\n### Pre/post identities and working-tree status\n\nAll five repositories have identical pre/post HEAD, branch, short status and diff-stat. All62 cited source files retain their captured hashes. This establishes no observed tracked/untracked status change and no change to cited file contents; it is not a claim that every uncited file was hashed. No live-process state was accessed or altered. Baseline mutable history was left alone, not reset.\n')
for a,v in repos.items():
 manifest.append(f'\n**{a}** = `{v["path"]}`, HEAD `{v["head"]}`, branch `{v["branch"]}`. Pre and post status:\n\n```text\n{v["status"] or "CLEAN"}\n```\n')
manifest.append('\n### Completion check\n\nAll37 requested G/C question IDs have explicit statuses and consequences; all8 shared contracts are mapped. Proposed interfaces/fixtures are labelled. Test presence and execution are separated. Main capsules plus both returned source supplements contain decisive implementation, including sampler dependencies. No sealed data, training, external calls, build, implementation or live change occurred. Baseline defects and document/code conflicts remain visible. Unknown empirical quantities are deferred. Discriminating tests include conflicting hidden worlds, nonconstant proxies, zero/nonzero event controls and harmful signals. Current installed binary/source correspondence and live process identity remain explicit limits.\n')
report=analysis+'\n'+(O/'capsules.tmp.txt').read_text()+'\n'+closing+'\n'+''.join(manifest)
assert not re.search(r'/Users/|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',report)
(O/'TUPPI_DESIGN_HANDOFF.md').write_text(report)
(O/'TUPPI_DESIGN_HANDOFF.txt').write_text(report)
# Structured questions from exact report headings.
expected=[f'G{i:02}' for i in range(1,11)]+[f'C{c}-{i:02}' for c,n in [(1,5),(2,5),(3,5),(4,6),(5,6)] for i in range(1,n+1)]
headers=list(re.finditer(r'^\*\*((?:G\d\d|C\d-\d\d)) \| (.*?)\*\*',analysis,re.M))
assert sorted(h[1] for h in headers)==sorted(expected)
def refs(s):
 out=[]
 for m in re.finditer(r'E(\d{3})(?:[–-]E(\d{3}))?',s):
  out.extend(f'E{x:03}' for x in range(int(m[1]),int(m[2] or m[1])+1))
 return list(dict.fromkeys(out))
questions=[]
for i,h in enumerate(headers):
 columns=h[2].split(' | ')
 assert len(columns)==4,(h[1],columns)
 evid=refs(columns[1]);assert all(x in byid for x in evid)
 end=headers[i+1].start() if i+1<len(headers) else analysis.index('\n## 4.')
 questions.append({'id':h[1],'status':columns[0],'evidence_ids':evid,'design_consequence':columns[2],'unresolved_item':columns[3],'answer_summary':analysis[h.end():end].strip().split('\n\n')[0]})
contracts=[('AgentSnapshot','PARTIAL'),('DecisionCase','PARTIAL'),('WorldBatch','PARTIAL'),('ActionWorldBatch','PARTIAL'),('PolicyFork','MISSING'),('DealTransition','PARTIAL'),('InformationKey','PARTIAL'),('ExperimentManifest','PARTIAL')]
interfaces=[]
for name,status in contracts:
 row=next(line for line in analysis.splitlines() if line.startswith('| '+name+' /'))
 interfaces.append({'name':name,'status':status,'proposed':True,'schema_description':row,'input_types':None,'output_types':None,'source_evidence':refs(row)})
# Exact existing Python signatures/types, without pretending unannotated parameters have declared types.
for id,names in {'E001':['best_agents'],'E003':['search_world_values','search_values','sample_world','observe','new_deal'],'E017':['observation_to_data','action_to_data','action_from_data'],'E022':['play_out','conditional_layouts'],'E023':['expected_ducking_tricks','card_liability'],'E025':['build_support','semantic_observation_key'],'E028':['hypothetical_continuation'],'E018':['create_match','begin_explicit_deal','apply_match_action']}.items():
 s=source(byid[id]).read_text();tree=ast.parse(s)
 for name in names:
  n=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
  args=n.args.posonlyargs+n.args.args+n.args.kwonlyargs
  types={a.arg:ast.unparse(a.annotation) if a.annotation else None for a in args}
  ret=ast.unparse(n.returns) if n.returns else None
  interfaces.append({'name':name,'status':'EXISTING','proposed':False,'signature':ast.unparse(n).split(':\n')[0],'input_types':types,'output_types':ret,'unannotated_type_semantics':'See native ABI and main report; null means no Python annotation, not inferred API.','source_evidence':[id],'lines':[n.lineno,n.end_lineno]})
fixtures=[]
for m in re.finditer(r'^([1-6])\. \*\*(F\d\d.*?)\*\* (.*?)(?=\n[1-6]\. \*\*|\nExisting wire fields)',closing,re.M|re.S):
 fixtures.append({'id':m[2].split()[0],'status':'PROPOSED','runtime_record':None,'construction':m[3].strip(),'evidence_ids':['E006','E016','E017']})
assert len(fixtures)==6
(O/'FIXTURE_RECIPES.json').write_text(json.dumps({'schema_version':'tuppi.audit.fixture_recipes.v1','fixtures':fixtures},indent=2)+'\n')
assets=json.loads((O/'asset_identities.json').read_text())
for rel,a in assets.items(): assert sha((R/rel).read_bytes())==a['sha256']
probes=[{'id':'P001','kind':'game_contract_probe','status':'NOT RUN','command':None,'timeout_seconds':20,'exit_status':None,'output':None,'wall_seconds':0},
 {'id':'M001','kind':'system_metadata','status':'BLOCKED','command':'sysctl -n machdep.cpu.brand_string hw.machine hw.ncpu hw.physicalcpu hw.logicalcpu hw.memsize','timeout_seconds':None,'exit_status':1,'output':'sysctl: sysctl fmt -1 1024 1: Operation not permitted'},
 {'id':'M002','kind':'system_metadata','status':'EXECUTED','commands':['sw_vers','python3 --version','clang --version','file TuppiAI/native/libtuppi.dylib'],'exit_status':0,'timeout_seconds':None,'output':{'os':'macOS 27.0 build 26A428','python':'3.14.2','compiler':'Apple clang 21.0.0 (clang-2100.1.1.101)','target':'arm64-apple-darwin27.0.0','native':'Mach-O 64-bit arm64'},'note':'Inventory only, not a game PROBE or benchmark.'}]
index={'schema_version':'tuppi.design_handoff.v1','repos':repos,'baseline':{'factory':'tuppi_ai.best.best_agents','ruleset':'project_target_v3','worlds':128,'tail':6,'clone':{'encoder':2,'width':256,'blocks':2,'input_width':1951},'assets':assets,'source_binary_correspondence':None,'historical_binary_sha256':None,'running_process_environment':None,'current_policy_state':None,'effective_factory_seed':'seed + 2*seat','sooli_defaults':{'give':'search','return':'heur','play':'search','belief':17,'lambda':0.3,'offer_play_heur':True,'offer_margin':0.02},'mutable_v3_configuration_bug_preserved':True,'entrypoint_evidence':['E001','E002','E013','E014','E015','E020','E059','E061']},'questions':questions,'interfaces':interfaces,'evidence':ev,'fixtures':fixtures,'blockers':[{'id':q['id'],'item':q['unresolved_item']} for q in questions],'probes':probes,'output_files':[]}
files=['TUPPI_DESIGN_HANDOFF.md','TUPPI_DESIGN_HANDOFF.txt','TUPPI_DESIGN_HANDOFF_INDEX.json','NATIVE_SOURCE_CAPSULES.txt','DEPENDENCY_SOURCE_CAPSULES.txt','FIXTURE_RECIPES.json','evidence.json','pre_state.json','post_state.json','asset_identities.json','capsule_omissions.json']
for f in files:
 p=O/f
 index['output_files'].append({'path':f,'bytes':p.stat().st_size if p.exists() and f!='TUPPI_DESIGN_HANDOFF_INDEX.json' else None,'sha256':sha(p.read_bytes()) if p.exists() and f!='TUPPI_DESIGN_HANDOFF_INDEX.json' else None})
index['output_files'].append({'path':'SHA256SUMS.txt','bytes':None,'sha256':None,'note':'External checksum list includes index hash; self-referential hashes intentionally null.'})
(O/'TUPPI_DESIGN_HANDOFF_INDEX.json').write_text(json.dumps(index,separators=(',',':'))+'\n')
# Readable sizes/hashes, not self-referential.
sums=[]
for f in files:
 b=(O/f).read_bytes();sums.append(f'{sha(b)}  {len(b):>9}  {f}')
(O/'SHA256SUMS.txt').write_text('SHA-256  bytes  relative path\n'+'\n'.join(sums)+'\n')
# Validate no personal home paths or email in exported text; schema parses and all referenced evidence exists.
for f in files+['SHA256SUMS.txt']:
 txt=(O/f).read_text()
 assert '/Users/' not in txt,f
 if f.endswith('.json'):json.loads(txt)
with zipfile.ZipFile(O/'TUPPI_DESIGN_HANDOFF_BUNDLE.zip','w',zipfile.ZIP_DEFLATED) as z:
 for f in files+['SHA256SUMS.txt']:z.write(O/f,arcname=f)
with zipfile.ZipFile(O/'TUPPI_DESIGN_HANDOFF_BUNDLE.zip') as z:assert z.testzip() is None
print(json.dumps({'questions':len(questions),'contracts':len(contracts),'fixtures':len(fixtures),'evidence_files':len(ev),'source_hashes_unchanged':True,'repo_statuses_unchanged':True,'files':[{'name':f,'bytes':(O/f).stat().st_size,'sha256':sha((O/f).read_bytes())} for f in ['TUPPI_DESIGN_HANDOFF.md','TUPPI_DESIGN_HANDOFF_INDEX.json','TUPPI_DESIGN_HANDOFF_BUNDLE.zip']]},indent=2))
