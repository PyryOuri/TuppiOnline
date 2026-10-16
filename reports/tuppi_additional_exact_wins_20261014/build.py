"""Private probes built from the preceding sealed comparator, never installed."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess
import sys

OUT = Path(__file__).resolve().parent
PREP = OUT.parent / 'tuppi_cheap_wins_preparation_20261014'
NATIVE = PREP / 'frozen/ai/native'
sys.path.insert(0, str(PREP))
from launch import verify
from build_native import candidate_sources, replace_once

STATS = '''
// Private probe metrics, aggregated once per chunk; not product telemetry.
static uint64_t probe_rows, probe_forced, probe_all_forced;
uint64_t tc_probe_rollout_metric(int which) {
  return which == 0 ? probe_rows : which == 1 ? probe_forced : probe_all_forced;
}
'''

POOL = '''
// Per-thread scratch with a thread-exit destructor. Model weights stay immutable.
typedef struct { float *h, *t, *u; size_t capacity; } ProbeScratch;
static pthread_key_t scratch_key;
static pthread_once_t scratch_once = PTHREAD_ONCE_INIT;
static __thread ProbeScratch *scratch_tls;
static void scratch_destroy(void *value) {
  ProbeScratch *s = value;
  if (s) { free(s->h); free(s->t); free(s->u); free(s); }
}
static void scratch_key_init(void) { pthread_key_create(&scratch_key, scratch_destroy); }
static ProbeScratch *scratch_get(size_t count) {
  if (!scratch_tls) {
    pthread_once(&scratch_once, scratch_key_init);
    scratch_tls = calloc(1, sizeof *scratch_tls);
    pthread_setspecific(scratch_key, scratch_tls);
  }
  ProbeScratch *s = scratch_tls;
  if (count > s->capacity) {
    free(s->h); free(s->t); free(s->u);
    s->h = malloc(sizeof(float) * count);
    s->t = malloc(sizeof(float) * count);
    s->u = malloc(sizeof(float) * count);
    s->capacity = count;
    __atomic_fetch_add(&probe_scratch_grows, 1, __ATOMIC_RELAXED);
  }
  return s;
}
// Explicit release for a retained main thread; worker thread exit releases itself.
void tc_probe_scratch_clear(void) {
  if (scratch_tls) {
    pthread_setspecific(scratch_key, NULL);
    scratch_destroy(scratch_tls);
    scratch_tls = NULL;
  }
}
'''


def environment(source, forced):
    start = source.index('static void play_out(')
    end = source.index('\nstatic int search_core', start)
    before, body, after = source[:start], source[start:end], source[end:]
    if forced:
        body = replace_once(body, '      int legal[TC_NUM_ACTIONS];\n      TcObs ob;',
            '      int legal_ids[rows][TC_NUM_ACTIONS], legal_count[rows], nforced = 0;\n      TcObs ob;')
        body = replace_once(body,
            '        tc_observe(d, d->cur, &ob);\n        tc_encode_v(&ob, feat + (size_t)r * dim, enc);',
            '        legal_count[r] = tc_legal(d, legal_ids[r]);\n'
            '        if (legal_count[r] == 1) {\n'
            '          nforced++;\n'
            '          // Keep every other row\'s position and matrix shape unchanged.\n'
            '          memset(feat + (size_t)r * dim, 0, (size_t)dim);\n'
            '        } else {\n'
            '          tc_observe(d, d->cur, &ob);\n'
            '          tc_encode_v(&ob, feat + (size_t)r * dim, enc);\n'
            '        }')
        body = replace_once(body, '      if (e->team_net && e->team_side >= 0) {',
            '      if (nforced < rows) {\n      if (e->team_net && e->team_side >= 0) {')
        body = replace_once(body,
            '        forward_games(e, m, idx + lo, rows, feat, dim, q);\n      }\n      for (int r = 0; r < rows; r++) {',
            '        forward_games(e, m, idx + lo, rows, feat, dim, q);\n      }\n      }\n      for (int r = 0; r < rows; r++) {')
        body = replace_once(body, '        int nl = tc_legal(d, legal), best = legal[0];',
            '        const int *legal = legal_ids[r];\n        int nl = legal_count[r], best = legal[0];')
        body = replace_once(body, '      free(feat);\n      free(q);',
            '      __atomic_fetch_add(&probe_rows, rows, __ATOMIC_RELAXED);\n'
            '      __atomic_fetch_add(&probe_forced, nforced, __ATOMIC_RELAXED);\n'
            '      if (nforced == rows) __atomic_fetch_add(&probe_all_forced, rows, __ATOMIC_RELAXED);\n'
            '      free(feat);\n      free(q);')
    else:
        body = replace_once(body, '      int legal[TC_NUM_ACTIONS];', '      int legal[TC_NUM_ACTIONS], nforced = 0;')
        body = replace_once(body, '        int nl = tc_legal(d, legal), best = legal[0];',
            '        int nl = tc_legal(d, legal), best = legal[0];\n        nforced += nl == 1;')
        body = replace_once(body, '      free(feat);\n      free(q);',
            '      __atomic_fetch_add(&probe_rows, rows, __ATOMIC_RELAXED);\n'
            '      __atomic_fetch_add(&probe_forced, nforced, __ATOMIC_RELAXED);\n'
            '      if (nforced == rows) __atomic_fetch_add(&probe_all_forced, rows, __ATOMIC_RELAXED);\n'
            '      free(feat);\n      free(q);')
    return before + STATS + body + after


def mlp(source, pool):
    source = source.replace('#include <stdlib.h>', '#include <stdlib.h>\n#include <pthread.h>')
    marker = '// out[rows][out_dim] for 0/1 features'
    stats = '''static uint64_t probe_mlp_calls, probe_mlp_rows, probe_scratch_grows;
uint64_t tc_probe_mlp_metric(int which) {
  return which == 0 ? probe_mlp_calls : which == 1 ? probe_mlp_rows : probe_scratch_grows;
}
'''
    source = replace_once(source, marker, stats + (POOL if pool else '') + '\n' + marker)
    start = source.index('void tc_mlp_forward(')
    end = source.index('// ------------------------------------------------ incremental first layer', start)
    before, body, after = source[:start], source[start:end], source[end:]
    body = replace_once(body, '  const int W = m->width;',
        '  __atomic_fetch_add(&probe_mlp_calls, 1, __ATOMIC_RELAXED);\n'
        '  __atomic_fetch_add(&probe_mlp_rows, rows, __ATOMIC_RELAXED);\n  const int W = m->width;')
    if pool:
        old = '\n'.join(f'  float *{v} = malloc(sizeof(float) * (size_t)rows * W);' for v in ('h', 't', 'u'))
        body = replace_once(body, old, '  ProbeScratch *s = scratch_get((size_t)rows * W);\n  float *h = s->h, *t = s->t, *u = s->u;')
        body = replace_once(body, '  free(h); free(t); free(u);', '  // Retained for this thread, with identical arithmetic and matrix shapes.')
    return before + body + after


def main():
    verify()
    build = OUT / 'builds'
    build.mkdir(exist_ok=False)
    base = {p.name: p.read_text() for p in NATIVE.iterdir() if p.suffix in {'.c', '.h'}}
    compiler = '/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/clang'
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'],
        env={'DEVELOPER_DIR': '/Applications/Xcode.app/Contents/Developer'}, text=True).strip()
    cfiles = ['tuppi_core.c', 'tuppi_env.c', 'tuppi_search.c', 'tuppi_dd.c', 'tuppi_mlp.c', 'tuppi_sooli.c', 'tuppi_sooli_policy.c']
    definitions = {'reference': (False, False, False), 'forced_rows': (True, False, False),
                   'scratch': (False, True, False), 'combined_speed': (True, True, True)}
    record = {'schema': 'tuppi.additional_exact_wins.build.v1',
              'base_package_sha256': hashlib.sha256((PREP/'PACKAGE.json').read_bytes()).hexdigest(), 'libraries': {}}
    for name, (forced, pool, buckets) in definitions.items():
        sources = candidate_sources() if buckets else dict(base)
        sources['tuppi_env.c'] = environment(sources['tuppi_env.c'], forced)
        sources['tuppi_mlp.c'] = mlp(sources['tuppi_mlp.c'], pool)
        folder = build/name; folder.mkdir()
        for filename, value in sources.items():
            (folder/filename).write_text(value)
            if value != base[filename]:
                (folder/(filename+'.patch')).write_text(''.join(difflib.unified_diff(base[filename].splitlines(True), value.splitlines(True), fromfile='frozen/'+filename, tofile=name+'/'+filename)))
        lib = folder/'libtuppi.dylib'
        command = [compiler,'-O3','-Wall','-Wextra','-Wno-unused-parameter','-isysroot',sdk,'-dynamiclib','-framework','Accelerate','-o',str(lib),*[str(folder/f) for f in cfiles]]
        result = subprocess.run(command, capture_output=True, text=True)
        (folder/'compiler.log').write_text(result.stdout+result.stderr)
        result.check_returncode()
        record['libraries'][name] = {'sha256':hashlib.sha256(lib.read_bytes()).hexdigest(), 'command':command,
            'sources':{filename:hashlib.sha256((folder/filename).read_bytes()).hexdigest() for filename in sources}}
        print('built',name,flush=True)
    with (OUT/'BUILD.json').open('x') as f: json.dump(record,f,indent=2)


if __name__ == '__main__': main()
