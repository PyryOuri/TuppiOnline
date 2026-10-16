"""Build reward buckets with optional forced-row compaction, without scratch reuse."""
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

OUT=Path(__file__).resolve().parent
PREP=OUT.parent/'tuppi_cheap_wins_preparation_20261014'
sys.path.insert(0,str(PREP))
from build_native import candidate_sources, replace_once
from launch import verify


def compact(source):
    start=source.index('static void play_out(')
    end=source.index('\nstatic int search_core',start)
    before,body,after=source[:start],source[start:end],source[end:]
    body=replace_once(body,'      int legal[TC_NUM_ACTIONS];\n      TcObs ob;',
        '      int legal_ids[rows][TC_NUM_ACTIONS], legal_count[rows], feature_slot[rows], nforced = 0, network_rows = 0;\n'
        '      const int compact = !e->team_net && !e->inc_on;\n      TcObs ob;')
    body=replace_once(body,'        tc_observe(d, d->cur, &ob);\n        tc_encode_v(&ob, feat + (size_t)r * dim, enc);',
        '        legal_count[r] = tc_legal(d, legal_ids[r]);\n'
        '        const int forced = legal_count[r] == 1;\n        nforced += forced;\n'
        '        feature_slot[r] = compact && forced ? -1 : compact ? network_rows++ : r;\n'
        '        if (feature_slot[r] >= 0) {\n          tc_observe(d, d->cur, &ob);\n'
        '          tc_encode_v(&ob, feat + (size_t)feature_slot[r] * dim, enc);\n        }')
    body=replace_once(body,'      if (e->team_net && e->team_side >= 0) {',
        '      if (nforced < rows) {\n      if (e->team_net && e->team_side >= 0) {')
    body=replace_once(body,
        '        forward_games(e, m, idx + lo, rows, feat, dim, q);\n      }\n      for (int r = 0; r < rows; r++) {',
        '        if (compact) tc_mlp_forward(m, feat, network_rows, q);\n'
        '        else forward_games(e, m, idx + lo, rows, feat, dim, q);\n      }\n      }\n      for (int r = 0; r < rows; r++) {')
    body=replace_once(body,'        int nl = tc_legal(d, legal), best = legal[0];',
        '        const int *legal = legal_ids[r];\n        int nl = legal_count[r], best = legal[0];')
    body=replace_once(body,
        '        const float *qr = q + (size_t)r * TC_NUM_ACTIONS;\n'
        '        for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];',
        '        if (nl > 1) {\n          const float *qr = q + (size_t)feature_slot[r] * TC_NUM_ACTIONS;\n'
        '          for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];\n        }')
    return before+body+after


def main():
    verify()
    build=OUT/'builds'; build.mkdir(exist_ok=False)
    native=PREP/'frozen/ai/native'
    original={p.name:p.read_text() for p in native.iterdir() if p.suffix in {'.c','.h'}}
    reward=candidate_sources()
    compiler='/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang'
    sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],env={'DEVELOPER_DIR':'/Applications/Xcode.app/Contents/Developer'},text=True).strip()
    cfiles=['tuppi_core.c','tuppi_env.c','tuppi_search.c','tuppi_dd.c','tuppi_mlp.c','tuppi_sooli.c','tuppi_sooli_policy.c']
    record={'schema':'tuppi.speed_qualification.build.v1','base_package_sha256':hashlib.sha256((PREP/'PACKAGE.json').read_bytes()).hexdigest(),'libraries':{}}
    for name in ('reward','reward_compact'):
        sources=dict(reward)
        if name=='reward_compact': sources['tuppi_env.c']=compact(sources['tuppi_env.c'])
        assert sources['tuppi_mlp.c']==original['tuppi_mlp.c'], 'No scratch pooling or inference instrumentation'
        folder=build/name; folder.mkdir()
        for filename,value in sources.items():
            (folder/filename).write_text(value)
            if value!=original[filename]:
                (folder/(filename+'.patch')).write_text(''.join(difflib.unified_diff(original[filename].splitlines(True),value.splitlines(True),fromfile='frozen/'+filename,tofile=name+'/'+filename)))
        library=folder/'libtuppi.dylib'
        command=[compiler,'-O3','-Wall','-Wextra','-Wno-unused-parameter','-isysroot',sdk,'-dynamiclib','-framework','Accelerate','-o',str(library),*[str(folder/f) for f in cfiles]]
        result=subprocess.run(command,capture_output=True,text=True)
        (folder/'compiler.log').write_text(result.stdout+result.stderr); result.check_returncode()
        record['libraries'][name]={'sha256':hashlib.sha256(library.read_bytes()).hexdigest(),'command':command,'sources':{f:hashlib.sha256((folder/f).read_bytes()).hexdigest() for f in sources}}
        print('built',name,flush=True)
    with (OUT/'BUILD.json').open('x') as f: json.dump(record,f,indent=2)


if __name__=='__main__': main()
