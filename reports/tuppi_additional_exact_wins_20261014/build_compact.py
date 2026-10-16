"""Optional forced-row compaction when a single exact rollout MLP is used."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess
from build import OUT, NATIVE, replace_once


def main():
    folder = OUT/'builds/compact_rows'; folder.mkdir(exist_ok=False)
    sources = {p.name:p.read_text() for p in (OUT/'builds/reference').iterdir() if p.suffix in {'.c','.h'}}
    source = (OUT/'builds/forced_rows/tuppi_env.c').read_text()
    source = replace_once(source,
        '      int legal_ids[rows][TC_NUM_ACTIONS], legal_count[rows], nforced = 0;',
        '      int legal_ids[rows][TC_NUM_ACTIONS], legal_count[rows], feature_slot[rows], nforced = 0, network_rows = 0;\n'
        '      const int compact = !e->team_net && !e->inc_on;')
    old = '''        legal_count[r] = tc_legal(d, legal_ids[r]);
        if (legal_count[r] == 1) {
          nforced++;
          // Keep every other row's position and matrix shape unchanged.
          memset(feat + (size_t)r * dim, 0, (size_t)dim);
        } else {
          tc_observe(d, d->cur, &ob);
          tc_encode_v(&ob, feat + (size_t)r * dim, enc);
        }'''
    new = '''        legal_count[r] = tc_legal(d, legal_ids[r]);
        const int forced = legal_count[r] == 1;
        nforced += forced;
        feature_slot[r] = compact && forced ? -1 : compact ? network_rows++ : r;
        if (feature_slot[r] >= 0) {
          tc_observe(d, d->cur, &ob);
          tc_encode_v(&ob, feat + (size_t)feature_slot[r] * dim, enc);
        }'''
    source = replace_once(source, old, new)
    source = replace_once(source,
        '        forward_games(e, m, idx + lo, rows, feat, dim, q);',
        '        if (compact) tc_mlp_forward(m, feat, network_rows, q);\n'
        '        else forward_games(e, m, idx + lo, rows, feat, dim, q);')
    start = source.index('static void play_out(')
    end = source.index('\nstatic int search_core',start)
    before, body, after = source[:start],source[start:end],source[end:]
    body = replace_once(body,
        '        const float *qr = q + (size_t)r * TC_NUM_ACTIONS;\n'
        '        for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];',
        '        if (nl > 1) {\n'
        '          const float *qr = q + (size_t)feature_slot[r] * TC_NUM_ACTIONS;\n'
        '          for (int t = 1; t < nl; t++) if (qr[legal[t]] > qr[best]) best = legal[t];\n'
        '        }')
    sources['tuppi_env.c']=before+body+after
    for name,value in sources.items():
        (folder/name).write_text(value)
        original=(NATIVE/name).read_text()
        if value!=original:
            (folder/(name+'.patch')).write_text(''.join(difflib.unified_diff(original.splitlines(True),value.splitlines(True),fromfile='frozen/'+name,tofile='compact_rows/'+name)))
    build=json.loads((OUT/'BUILD.json').read_text())
    command=[part.replace(str(OUT/'builds/reference'),str(folder)) for part in build['libraries']['reference']['command']]
    result=subprocess.run(command,capture_output=True,text=True)
    (folder/'compiler.log').write_text(result.stdout+result.stderr); result.check_returncode()
    record={'schema':'tuppi.additional_exact_wins.compact_build.v1','command':command,
            'library_sha256':hashlib.sha256((folder/'libtuppi.dylib').read_bytes()).hexdigest(),
            'sources':{name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in sources},
            'scope':'Compaction only when no team split or incremental first-layer state is enabled; current same-model rollout factory.'}
    with (OUT/'COMPACT_BUILD.json').open('x') as f: json.dump(record,f,indent=2)
    print('built compact_rows',flush=True)


if __name__=='__main__': main()
