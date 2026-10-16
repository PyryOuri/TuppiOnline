"""Write the integration record only after all publication and test gates pass."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

audit = Path(__file__).resolve().parent
root = audit.parents[1]


def read(name):
    return json.loads((audit / name).read_text())


gates = ['PROMOTION.json', 'HOSTED_HTTP_CHECKS.json', 'checks/release-regressions.json',
    'checks/linux-image-game.json', 'checks/native-oracles-macos.json', 'checks/native-oracles-linux.json',
    'checks/frozen-models-preserved.json', 'checks/context-preserved.json', 'checks/cleanup.json',
    *[f'checks/{backend}-w{worlds}-parity.json' for backend in ('macos', 'wasm') for worlds in (128, 1024)],
    *[f'checks/{backend}-pair-{number}-exact.json' for backend in ('macos', 'linux', 'wasm') for number in (1, 2, 3)]]
for name in gates:
    assert read(name)['passed'], name
deployment = read('SITE_DEPLOYMENT.json')
assert deployment['status'] == 'succeeded'
timing = read('checks/TIMING_SUMMARY.json')
assert all(value['passed_exact'] for value in timing['backends'].values())
sources = {}
for name in ('TuppiAI-hosted', 'TuppiBrowser', 'TuppiBrowser-offline-release', 'TuppiProject-browser-network', 'deploy/TuppiOffline'):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root / name, text=True).strip()
    sources[name] = {'commit': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
                     'status': git('status', '--porcelain')}
    assert not sources[name]['status'], name
(audit / 'SOURCES.json').write_text(json.dumps(sources, indent=2) + '\n')

package = root / 'audit_deliverables/tuppi_speed_qualification_20261014'
sealed = json.loads((package / 'PACKAGE.json').read_text())
for name, digest in sealed['files'].items():
    assert hashlib.sha256((package / name).read_bytes()).hexdigest() == digest, name
offline = read('OFFLINE_RELEASE.json')
image = read('checks/linux-image-game.json')
validation = {'schema': 'tuppi.compact128.integration.validation.v1', 'passed': True,
    'completed_utc': datetime.now(timezone.utc).isoformat(), 'gates': gates,
    'source_commits': sources, 'sealed_original_files_verified': len(sealed['files']),
    'offline_release': offline['release'], 'runtime_identity': offline['frontend']['runtime_identity'],
    'site_deployment': deployment, 'linux_image': image['image'],
    'pending': ['physical iPhone installation/offline/lifecycle/performance acceptance',
        'native production-host capacity qualification and hosting/billing selection',
        'public friends/network release'],
    'scope': 'Qualified compact128 integration and finite exactness/timing; no training, new research mechanisms, strength claim, live native replacement or paid hosting'}
(audit / 'VALIDATION.json').write_text(json.dumps(validation, indent=2) + '\n')

rows = []
for key, title in [('macos', 'macOS portable Accelerate'), ('linux', 'Linux x86-64 OpenBLAS via Rosetta'), ('wasm', 'Node WebAssembly SIMD')]:
    value = timing['backends'][key]['median_paired']
    rows.append(f"| {title} | {100 * value['cpu_reduction']:.1f}% | {100 * (1-value['decision_p95_ratio']):.1f}% | {100 * (1-value['bid_p95_ratio']):.1f}% |")
commits = '\n'.join(f"| `{name}` | `{value['commit']}` |" for name, value in sources.items())
report = f'''# Compact128 browser and hosted-bot integration

Completed 14 October 2026. The user authorised this product integration after
the feasibility review. Only the already-qualified compact128 mechanisms were
ported; the original research packages remain unchanged.

## Delivered changes

The portable native core now evaluates exact endgame reward buckets from the
loaded equity table, shares identical VRPO1 rollout weights, uses rollout batches
of 128 and skips neural inference for forced rows. Settings belong to each
controller. Environments and random streams remain separate; reference
computation remains available for differential checks.

Models, W128/W1024 budgets, adaptive bidding, margins, six-trick tail,
showing-fallback fix and the existing sooli lifecycle/settings are unchanged.
The exact-trick solver API is retained. Reward-only certificates remain private
to the root evaluator; capture/value-learning paths do not fabricate terminal
deals. No one-row padding, reference change, budget ladder or new research
mechanism was introduced.

The browser and hosted candidates use the same portable sources. Build and model
export tools now select `TuppiAI-hosted` explicitly and write into their own
browser checkout. The tested native library and seven browser assets were
promoted without rebuilding different runtime bytes. UI styles and interactions
were preserved. The live Swift application/server and original research
checkouts were not replaced.

## Measured performance

Three serial paired rounds per backend used two fixed synthetic deal inputs at
scores 24–0 and 40–0, W1024, 118 choices/probes and eight bids per job. Order was
baseline/candidate, candidate/baseline, baseline/candidate. CPU includes job
setup; p95 durations use linear interpolation. These are median paired
reductions on this finite bank:

| Backend | Job CPU | Decision p95 | Bid p95 |
|---|---:|---:|---:|
{chr(10).join(rows)}

The separate zero-score W1024 WASM pair reduced CPU by 11.7%; this shows that the
gain depends on the workload. No strength, battery, physical iPhone, arbitrary
game or production-host performance guarantee follows from these measurements.
Linux ran in a one-CPU ARM64 Lima VM through Rosetta, rather than on a native
production x86-64 host. All compute qualification jobs ran serially with one
BLAS/Torch thread. Raw measurements are in `checks/TIMING_SUMMARY.json`.

## Correctness and recovery

- W128 and W1024 Mac native and actual Node WASM comparisons passed. The browser
  cases replay 396 actions and 1,584 feature views, both models, 113 natural
  controller decisions and five forced sooli probes at each budget.
- Paired comparisons require exact actions, float64 value bits, RNG cursors and
  retained per-seat sooli options within each backend. Cross-backend model and
  price comparisons retain their established tolerances; exactness is not
  asserted across different arithmetic backends.
- On macOS and Linux, 168 exact reward-oracle checks cover 56 positions, all 25
  score cells, both contracts, one to seven remaining tricks and partial tricks.
  Both frozen models had zero sampled float32 batch differences at batch sizes
  1, 2, 3, 7, 31, 32, 33, 127, 128, 129 and 257 against the full 32-row reference.
  This does not certify every floating-point path on an untested host.
- The Linux image passed its frozen W128/W1024 build gate and direct exact paired
  comparisons with the retained old image. Its full game used one human adapter
  and three trained W1024 bots: {image['match']['completedDeals']} deals,
  {image['match']['actions']} human actions, score {image['match']['finalScores'][0]}–{image['match']['finalScores'][1]}.
  Uncertain-action reconnect, reload, midgame restart, replacement-container
  volume restore, a two-human partner lobby, private projections, origin/file
  boundaries and non-root/private storage checks passed. This functional game
  used a deliberately poor human policy; it is not a strength or paired speed
  result.
- The functional container peak was {int(image['limits']['memory.peak']):,} bytes
  under a 2 GiB cap. This cap is a test configuration, not a minimum hosting
  requirement. Host sizing and lower-cost options remain to be qualified.
- Source and packaged table/keyboard/reveal, network, offline update/cache,
  storage, recovery, session restore and real generated worker startup checks
  passed. See `checks/release-regressions.json`. These Node adapters do not
  establish browser rendering, authentication, cross-tab or device acceptance.

All three frozen source model/table hashes and browser model exports are
unchanged. All {len(sealed['files'])} files in the original qualified package
were reverified. The original 200-deal research result is supporting evidence
for that original comparator; this report records the separate product port.

## Released artifacts and sources

The existing owner-private offline Site was updated using the Sites source and
publication workflow. Its audience is unchanged:
{deployment['url']}

Published offline release: `{offline['release']}`.
Runtime identity: `{offline['frontend']['runtime_identity']}`.
The current offline inventory contains {offline['files']} distribution files;
cache budget {offline['cache_bytes']:,} bytes. Authenticated HTTPS retrieval
verified every current distribution file, JavaScript/WASM MIME and exact
plain-text HTML shells. Host-added document decoration is recorded separately.

The Site retains all previous immutable launch/runtime files. Older saves remain
pinned to their compatible runtime and do not receive a computation change
mid-match. A pre-update save can therefore route to the old runtime; automatic
save migration and a release selector are outside this integration. Qualify the
new runtime using a storage context without an old save, preserving existing
games and exported backups. `IPHONE_ACCEPTANCE.md` identifies the new release
and remaining user-run checks.

| Checkout | Promoted source commit |
|---|---|
{commits}

The sealed, provider-neutral image context is `deploy/TuppiNetwork-compact128`:
508 hashed files, 42,794,538 bytes. Its `SOURCE.json` records the build-input
commits; later checker/tool/documentation commits do not change its runtime
sources. Qualified image ID: `{image['image']['id']}`. Existing context
`deploy/TuppiNetwork` and its old image remain as rollback evidence. The owned
test containers/volumes were removed and the local VM stopped.

## Reproduction and limits

`PLAN.json`, `BUILD.json`, `PROMOTION_PLAN.json`, `PROMOTION.json`, `SOURCES.json`,
final source patches, per-job records and `VALIDATION.json` preserve the inputs
and gates. The fixed job drivers refuse to overwrite existing evidence. To
repeat Mac comparisons after promotion, recreate the baseline checkout at
`fbad9c4f58824c664e1315a79f5f3eff56ed36ec` with the retained baseline library;
do not use the now-updated hosted checkout as the old implementation. WASM's
old runtime and assets are retained under `baseline-wasm/`. Linux image IDs are
recorded in `checks/linux-comparison-images.json`.

Direct Safari/Tuppi app UI access remains declined. Physical iPhone 17 Pro Max
installation, actual iOS version, offline launch, suspension, storage and heat/
battery/latency acceptance remain pending. Hosting is undecided. No paid service,
public online release, new training or live native replacement was performed.
'''
(audit / 'REPORT.md').write_text(report)
progress = read('PROGRESS.json')
progress.update({'time_utc': validation['completed_utc'], 'phase': 'Completed', 'current_jobs': {},
    'pending': validation['pending'], 'validation': 'VALIDATION.json', 'report': 'REPORT.md', 'vm': 'stopped'})
(audit / 'PROGRESS.json').write_text(json.dumps(progress, indent=2) + '\n')
print(json.dumps({'passed': True, 'report': str(audit / 'REPORT.md'), 'site': deployment['url']}))
