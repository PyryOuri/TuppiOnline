#!/usr/bin/env python3
"""Build the portable runtime with the workspace's pinned Emscripten SDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

browser = Path(__file__).resolve().parents[1]
root = browser.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ai', type=Path, default=root / 'TuppiAI-hosted')
parser.add_argument('--threads', action='store_true', help='Build the shared-memory inference backend')
parser.add_argument('--reference-kernel', action='store_true', help='Retain the original four-column SIMD kernel')
parser.add_argument('--output', type=Path, help='Separate build directory for qualification')
args = parser.parse_args()
native = args.ai.resolve() / 'native'
sdk = root / "toolchains/emsdk"
out = args.output.resolve() if args.output else browser / "web/assets"
out.mkdir(parents=True, exist_ok=True)
sources = [native / name for name in ("tuppi_core.c", "tuppi_env.c", "tuppi_search.c", "tuppi_dd.c",
           "tuppi_mlp.c", "tuppi_sooli.c", "tuppi_sooli_policy.c", "tuppi_dd_wr.c", "tuppi_lite_net.c", "tuppi_browser.c")]
functions = ["malloc", "free", "tb_api_version", "tb_load_model", "tb_configure", "tb_init", "tb_legal",
             "tb_apply", "tb_state", "tb_hand", "tb_history", "tb_bids", "tb_choose", "tb_values",
             "tb_context", "tb_restore_context", "tb_configure_bot", "tb_restore_net_context", "tb_observation_size", "tb_observation", "tb_features", "tb_inference"]
functions += ['tb_configure_inference', 'tb_belief_profile', 'tb_dispose']
module_name = 'tuppi-thread' if args.threads else 'tuppi'
extra = ['-DTC_WASM_REFERENCE=1'] if args.reference_kernel else []
if args.threads:
    extra += ['-pthread', '-sPTHREAD_POOL_SIZE=3', '-sPTHREAD_POOL_SIZE_STRICT=2',
              '-sPTHREAD_POOL_DELAY_LOAD=0', '-sDEFAULT_PTHREAD_STACK_SIZE=2097152',
              '--post-js', str(browser / 'tools/thread_runtime.js')]
command = [sys.executable, str(sdk / "upstream/emscripten/emcc.py"), *map(str, sources),
           "-O3", "-msimd128", "-ffp-contract=off", "-DTC_PORTABLE=1", "-I", str(native),
           "-sMODULARIZE=1", "-sEXPORT_ES6=1", "-sENVIRONMENT=web,worker,node",
           "-sALLOW_MEMORY_GROWTH=1", "-sINITIAL_MEMORY=67108864", "-sMAXIMUM_MEMORY=268435456",
           "-sSTACK_SIZE=4194304", "-sEXPORTED_FUNCTIONS=" + json.dumps(["_" + f for f in functions]),
           "-sEXPORTED_RUNTIME_METHODS=" + json.dumps(["HEAPU8", "HEAP32", "HEAPF32", "HEAPF64"] + (['PThread'] if args.threads else [])),
           *extra, "-o", str(out / (module_name + '.mjs'))]
env = {**os.environ, "EM_CONFIG": str(sdk / ".emscripten"),
       "EM_CACHE": str(sdk / "upstream/emscripten/cache")}
subprocess.run(command, env=env, check=True)
version = subprocess.run([sys.executable, str(sdk / "upstream/emscripten/emcc.py"), "--version"],
                         env=env, check=True, capture_output=True, text=True).stdout.splitlines()[0]
records = [{"file": p.name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
           for p in (out / (module_name + '.mjs'), out / (module_name + '.wasm'))]
extra_sources = [browser / 'tools/thread_runtime.js'] if args.threads else []
identity = {"compiler": version, "command": command,
            "sources": [{"path": str(p.relative_to(root)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                        for p in sources + sorted(native.glob("*.h")) + extra_sources], "outputs": records}
previous = json.loads((out / 'build.json').read_text()) if (out / 'build.json').exists() else {}
variants = previous.get('variants', {})
variants['threads' if args.threads else 'single'] = identity
manifest = {"schema": "tuppi.browser.build.v1", "compiler": version,
            "variants": variants, "outputs": [record for variant in variants.values() for record in variant['outputs']]}
(out / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"compiler": version, "outputs": manifest["outputs"]}))
