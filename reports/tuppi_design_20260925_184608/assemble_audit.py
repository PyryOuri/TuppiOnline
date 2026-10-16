"""Static audit packaging only. Does not import project modules or execute game code."""
from pathlib import Path
import ast, hashlib, json, subprocess, re, zipfile
OUT=Path(__file__).resolve().parent
ROOT=OUT.parent.parent
REPOS=json.loads((OUT/'pre_state.json').read_text())
SPECS=[
('E001','AI','tuppi_ai/best.py','CODE'),
('E002','AI','tuppi_ai/search.py','CODE'),
('E003','AI','tuppi_ai/native.py','CODE'),
('E004','AI','native/tuppi_env.c','CODE'),
('E005','AI','native/tuppi_search.c','CODE'),
('E006','AI','native/tuppi_core.h','CODE'),
('E007','AI','native/tuppi_core.c','CODE'),
('E008','AI','native/tuppi_sooli_policy.c','CODE'),
('E009','AI','native/tuppi_dd.c','CODE'),
('E010','AI','native/tuppi_sooli.c','CODE'),
('E011','AI','tuppi_ai/bridge.py','CODE'),
('E012','AI','tuppi_ai/equity.py','CODE'),
('E013','AI','tuppi_ai/evaluate.py','CODE'),
('E014','AI','tuppi_ai/match_eval.py','CODE'),
('E015','AI','tuppi_ai/review.py','CODE'),
('E016','ENGINE','src/tuppi_engine/observations.py','CODE'),
('E017','ENGINE','src/tuppi_engine/serialization.py','CODE'),
('E018','ENGINE','src/tuppi_engine/match.py','CODE'),
('E019','ENGINE','src/tuppi_rules/match.py','CODE'),
('E020','ENGINE','src/tuppi_server/match_runner.py','CODE'),
('E021','ENGINE','src/tuppi_server/rooms.py','CODE'),
('E022','RESEARCH','src/tuppi_valuation/suits.py','CODE'),
('E023','RESEARCH','src/tuppi_agents/nolo_discard.py','CODE'),
('E024','RESEARCH','tests/agents/test_nolo_discard.py','TEST'),
('E025','RESEARCH','src/tuppi_nolo/support.py','CODE'),
('E026','RESEARCH','src/tuppi_nolo/security.py','CODE'),
('E027','ENGINE','src/tuppi_exact/constraints.py','CODE'),
('E028','ENGINE','src/tuppi_exact/continuation.py','CODE'),
('E029','ENGINE','src/tuppi_search/fast_trick.py','CODE'),
('E030','AI','tools/sooli_bank.py','CODE'),
('E031','AI','tools/sooli_play_eval.py','CODE'),
('E032','AI','tools/gen_game_db.py','CODE'),
('E033','AI','tuppi_ai/bc.py','CODE'),
('E034','AI','tuppi_ai/distill.py','CODE'),
('E035','AI','tuppi_ai/model.py','CODE'),
('E036','AI','tools/fit_equity.py','CODE'),
('E037','AI','docs/STATUS.md','REPORT'),
('E038','AI','tests/test_sampler.py','TEST'),
('E039','AI','tests/test_sampler_v2.py','TEST'),
('E040','AI','tests/test_sooli_solver.py','TEST'),
('E041','ENGINE','tests/engine/test_locked_bids_engine.py','TEST'),
('E042','ENGINE','tests/engine/test_sooli_engine.py','TEST'),
('E043','ENGINE','tests/engine/test_sooli_locked_serialization.py','TEST'),
('E044','RESEARCH','docs/agents/architecture.md','REPORT'),
('E045','RESEARCH','docs/exact/architecture.md','REPORT'),
('E046','RESEARCH','docs/match/bank_lifecycle.md','REPORT'),
('E047','RESEARCH','tests/agents/test_architecture.py','TEST'),
('E048','RESEARCH','tests/search/test_architecture.py','TEST'),
('E049','CLIENT','Sources/TuppiClient/ReferencePolicy.swift','CODE'),
('E050','AI','native/build.sh','CODE'),
('E051','ENGINE','src/tuppi_engine/transitions.py','CODE'),
('E052','ENGINE','src/tuppi_rules/showing.py','CODE'),
('E053','RESEARCH','docs/nolo/results/N11.md','REPORT'),
('E054','RESEARCH','docs/nolo/tasks/README.md','REPORT'),
('E055','ENGINE','src/tuppi_exact/counting.py','CODE'),
('E056','ENGINE','src/tuppi_exact/sampling.py','CODE'),
('E057','ENGINE','configs/rules/project_target_v3.json','REPORT'),
('E058','AI','docs/BIDDING_EXPLANATION_PLAN.md','REPORT'),
('E059','AI','tools/serve_human.py','CODE'),
('E060','AI','tuppi_ai/incumbent.py','CODE'),
('E061','ENGINE','src/tuppi_server/real_game_deal_analysis.py','CODE'),
('E062','AI','docs/HUMAN_BENCHMARK.md','REPORT'),
]
def digest(b): return hashlib.sha256(b).hexdigest()
def clean(s):
    s=re.sub(r'/Users/[^/\s]+', '<LOCAL_HOME>', s)
    s=re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '<REDACTED_EMAIL>', s)
    return s
E=[]; texts={}; omissions=[]
for id,repo,path,kind in SPECS:
    p=ROOT/REPOS[repo]['path']/path
    if not p.exists():
        omissions.append(f'{id}: requested evidence path {repo}:{path} does not exist; no fabricated source.')
        continue
    b=p.read_bytes(); s=b.decode(); texts[id]=s
    symbols=[]
    if p.suffix=='.py':
        tree=ast.parse(s)
        for n in ast.walk(tree):
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                symbols.append({'symbol':n.name,'lines':[n.lineno,n.end_lineno]})
    E.append(dict(evidence_id=id,repo=repo,path=path,symbol='file; symbols below',lines=[1,len(s.splitlines())],sha256=digest(b),type=kind,symbols=symbols,test_execution='NOT RUN' if kind=='TEST' else None))
# Exact selections; other complete relevant definitions remain in supplementary excerpts when requested below.
CAPS={
'E001':['best_agents'], 'E011':['mask_of','action_id','engine_action','obs_from_player_observation'], 'E059':['_plan','main'], 'E060':['incumbent_agents'], 'E002':['Searcher','SearchAgent'],
'E003':['TcDeal','TcObs','search_world_values','search_values','Env','Mlp'],
'E012':['DealModel','solve','native_table','Equity'],
'E013':['_init','_make_candidate','_score_for','_play','measure','summarise','evaluate'],
'E014':['_leg','measure_pair','evaluate_matches'],
'E016':['PlayerObservation','_observation_for_validated'],
'E017':['action_to_data','_sooli_observation_data','observation_to_data','_observation_data'],
'E019':['transition_rising_score'],
'E022':['SuitPolicy','play_out','conditional_layouts'],
'E023':['ducking_probabilities','expected_ducking_tricks','card_liability','public_conditioning'],
'E024':['test_contested_rounds_match_a_brute_force_walk'],
'E025':['SupportBudget','ResearchWorld','SupportResult','semantic_observation_key','build_support'],
'E026':['_search'],
'E028':['hypothetical_continuation'],
'E020':['_construct_ai_agents','_resolve_locked_showing'],
'E027':['show_exclusion_for'],
}
# Main capsules contain complete decisive code, supplemental code covers the surrounding glue.
MAIN={'E001','E002','E003','E012','E013','E014','E016','E017','E019','E022','E023','E024','E025','E026','E028','E020','E027'}
cap=['## 6. Source capsules\n\nThese are static source excerpts, not executed examples. Line ranges and hashes identify the original files. Comments are source claims, not audit validation. Type definitions precede the native evaluator. Python imports and unrelated functions are omitted; dependencies are identified in the interface inventory and evidence manifest. Full selected C files are included in `NATIVE_SOURCE_CAPSULES.txt` because splitting their tightly coupled helpers would obscure sampling and RNG semantics. That file is part of this bundle. No executable candidate is supplied.\n']
for id,names in CAPS.items():
    if id not in texts: continue
    nodes=list(ast.walk(ast.parse(texts[id])))
    lines=texts[id].splitlines()
    parts=[]
    for name in names:
        found=[n for n in nodes if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name==name]
        if not found:
            omissions.append(f'{id}: capsule symbol {name} not found; inspect listed symbol index; not claimed present.')
            continue
        n=found[0]; start=min([n.lineno]+[x.lineno for x in getattr(n,'decorator_list',[])])
        parts.append(f'### {id} — {name}, lines {start}–{n.end_lineno}\n\n```python\n'+clean('\n'.join(lines[start-1:n.end_lineno]))+'\n```\n')
    cap.extend(parts)
# Complete core structs and complete batching/RNG/evaluation implementation directly in main.
for id in ['E006','E004']:
    if id in texts: cap.append(f'### {id} — complete native contract / evaluator\n\n```c\n'+clean(texts[id])+'\n```\n')
# Native sampler and sooli logic complete in bundled supplement, compact decisive excerpts also main.
for id,lo,hi in [('E005',276,339),('E008',283,320)]:
    cap.append(f'### {id} — decisive sampler entrypoint, lines {lo}–{hi}\n\n```c\n'+clean('\n'.join(texts[id].splitlines()[lo-1:hi]))+'\n```\n')
(OUT/'NATIVE_SOURCE_CAPSULES.txt').write_text('\n\n'.join(f'{id} | {next(e["path"] for e in E if e["evidence_id"]==id)} | complete file\n'+clean(texts[id]) for id in ['E005','E007','E008','E009','E010'] if id in texts))
(OUT/'capsules.tmp.txt').write_text('\n'.join(cap))
(OUT/'evidence.json').write_text(json.dumps(E,indent=2)+'\n')
(OUT/'capsule_omissions.json').write_text(json.dumps(omissions,indent=2)+'\n')
print(json.dumps({'evidence_files':len(E),'capsule_omissions':omissions,'main_capsule_bytes':(OUT/'capsules.tmp.txt').stat().st_size}))
