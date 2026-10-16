"""Serial source and generated-release adapter checks; no browser automation."""
import json
from pathlib import Path
import subprocess
import time

audit = Path(__file__).resolve().parent
root = audit.parents[1]
node = root / 'toolchains/emsdk/node/24.19.0_64bit/bin/node'
reference = audit / 'checks/candidate-macos-w128.json'
results = []
target = audit / 'checks/release-regressions.json'
if target.exists():
    raise RuntimeError('Refusing to overwrite existing regression evidence')
for name in ('TuppiBrowser-speed-port', 'TuppiBrowser-offline-release'):
    checkout = root / name
    frontend = json.loads((checkout / 'web/frontend.json').read_text())
    cases = [('table-source', 'check_table.mjs', []),
             ('table-packaged', 'check_table.mjs', [str(checkout / 'web' / frontend['client'])])]
    if name == 'TuppiBrowser-speed-port':
        cases += [('table-online-source', 'check_table.mjs', ['--online']),
                  ('table-online-packaged', 'check_table.mjs', [str(checkout / 'web' / frontend['client']), '--online']),
                  ('network', 'check_network.mjs', [])]
    cases += [(test, 'check_' + test + '.mjs', []) for test in
              ('offline', 'offline_setup', 'storage', 'recovery', 'startup')]
    cases += [('session', 'check_session.mjs', [str(reference)])]
    for label, script, args in cases:
        command = [str(node), str(checkout / 'tests' / script), *args]
        started = time.monotonic()
        process = subprocess.run(command, cwd=checkout, text=True, capture_output=True, timeout=180)
        record = {'checkout': name, 'case': label, 'command': command,
                  'passed': process.returncode == 0, 'elapsed_seconds': time.monotonic() - started,
                  'stdout': process.stdout, 'stderr': process.stderr}
        results.append(record)
        print(json.dumps({key: record[key] for key in ('checkout', 'case', 'passed', 'elapsed_seconds')}), flush=True)
        if process.returncode:
            target.write_text(json.dumps({'passed': False, 'checks': results}, indent=2) + '\n')
            raise RuntimeError(process.stderr)
target.write_text(json.dumps({'passed': True, 'checks': results,
    'scope': 'Node DOM/cache/worker/storage adapters and actual generated WASM startup; no browser/device acceptance'}, indent=2) + '\n')
