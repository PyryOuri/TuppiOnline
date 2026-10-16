"""Promote only tested source commits and exact prebuilt local artifacts."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

audit = Path(__file__).resolve().parent
root = audit.parents[1]
for name in ['linux-image-game.json', 'release-regressions.json',
             *[f'{backend}-pair-{number}-exact.json' for backend in ('macos', 'linux', 'wasm') for number in (1, 2, 3)]]:
    check = json.loads((audit / 'checks' / name).read_text())
    assert check.get('passed', check.get('passed_exact', False)), name


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=root / repo, text=True).strip()


plan = json.loads((audit / 'PROMOTION_PLAN.json').read_text())
for row in plan:
    assert git(row['destination'], 'rev-parse', 'HEAD') == row['base_commit']
    assert git(row['candidate'], 'rev-parse', 'HEAD') == row['candidate_commit']
    assert not git(row['destination'], 'status', '--porcelain')
    assert not git(row['candidate'], 'status', '--porcelain')
for row in plan:
    git(row['destination'], 'merge', '--ff-only', row['candidate_commit'])
    print('Promoted ' + row['destination'], flush=True)

native = root / 'TuppiAI-speed-port/native/libtuppi.dylib'
expected = json.loads((audit / 'BUILD.json').read_text())['candidate_macos_library_sha256']
assert hashlib.sha256(native.read_bytes()).hexdigest() == expected
shutil.copyfile(native, audit / 'compact128-hosted.dylib')
shutil.copyfile(native, root / 'TuppiAI-hosted/native/libtuppi.dylib')
assets = ['tuppi.mjs', 'tuppi.wasm', 'build.json', 'models.json', 'equity.f64',
          'vrpo1_actor_0504.f32', 'vrpo3_final.f32']
for name in assets:
    shutil.copyfile(root / 'TuppiBrowser-speed-port/web/assets' / name,
                    root / 'TuppiBrowser/web/assets' / name)
subprocess.run(['python3', 'tools/package_offline.py'], cwd=root / 'TuppiBrowser', check=True)
assert (root / 'TuppiBrowser/web/offline-manifest.json').read_bytes() == (root / 'TuppiBrowser-speed-port/web/offline-manifest.json').read_bytes()
for row in plan:
    assert git(row['destination'], 'rev-parse', 'HEAD') == row['candidate_commit']
    assert not git(row['destination'], 'status', '--porcelain')
(audit / 'PROMOTION.json').write_text(json.dumps({'passed': True, 'sources': plan,
    'native_sha256': expected, 'browser_release': json.loads((root / 'TuppiBrowser/web/offline-manifest.json').read_text())['release'],
    'scope': 'Owned browser/hosted checkouts only; no original research or running native replacement'}, indent=2) + '\n')
