"""Is one row's native MLP output bitwise independent of its batch?

Compaction and chunk 128 change only which rows share a cblas_sgemm call.
If every row's output is identical alone, at any batch size and position,
those changes cannot alter a rollout argmax, even at exact ties.
"""
import argparse, ctypes as C, hashlib, json, random, sys, time
from pathlib import Path
QUAL = Path(__file__).resolve().parent.parent / 'tuppi_speed_qualification_20261014'
sys.path.insert(0, str(QUAL))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--variant', default='compact128')
    ap.add_argument('--deals', type=int, default=120); ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    from bindings import activate
    candidates, native, best = activate(a.variant)
    import numpy as np, torch
    models = {'vrpo1_rollout': candidates.loaded(str(best.OPPONENT_ROLLOUT)), 'vrpo3_anchor': candidates.loaded(str(best.ANCHOR))}
    # Realistic inputs: every decision state of random legal ruleset-3 deals,
    # with sooli accepted when offered so its phases are present.
    rows, phases = [], {}
    for k in range(a.deals):
        rng = random.Random(f'mlp-invariance|{k}'); deck = list(range(52)); rng.shuffle(deck)
        hands = [sum(1 << c for c in deck[s*13:(s+1)*13]) for s in range(4)]
        cell = k % 25; score = (4*cell, 0) if cell <= 12 else (0, 4*(cell-12))
        d = native.new_deal(hands, k % 4, *score, ruleset=3)
        while d.phase != native.PH_DONE:
            ob = native.observe(d, d.cur); rows.append(ob); phases[int(d.phase)] = phases.get(int(d.phase), 0) + 1
            legal = native.legal(d)
            act = native.ACT_SOOLI_ACCEPT if d.phase == native.PH_SOOLI_OFFER and native.ACT_SOOLI_ACCEPT in legal and k % 2 else rng.choice(legal)
            assert native.lib.tc_apply(C.byref(d), act) == 0
    report = {'variant': a.variant, 'library': str(native._LIB_PATH), 'rows': len(rows), 'phase_counts': phases, 'models': {}}
    for name, net in models.items():
        m = native.Mlp(net)
        feat = np.stack([native.encode(o, encoder=m.encoder) for o in rows])
        single = np.concatenate([m.forward(feat[i:i+1]) for i in range(len(feat))])
        t0 = time.time(); checks = mismatched_rows = 0; worst = 0.0; failures = []
        prng = np.random.default_rng(20261014)
        sizes = list(range(1, 300)) + [383, 512, 1000, 1024, 2048]
        for M in sizes:
            for trial in range(4 if M < 300 else 2):
                pick = prng.choice(len(feat), size=M, replace=M > len(feat)) if trial else (np.arange(M) % len(feat))
                out = m.forward(feat[pick]); want = single[pick]
                bad = np.any(out.view(np.uint32) != want.view(np.uint32), axis=1)
                checks += M; mismatched_rows += int(bad.sum())
                if bad.any():
                    worst = max(worst, float(np.max(np.abs(out[bad] - want[bad]))))
                    if len(failures) < 10: failures.append({'M': M, 'trial': trial, 'rows': int(bad.sum())})
        # Same full batch run twice, and the whole corpus as one batch.
        full = m.forward(feat)
        report['models'][name] = {'width': m.width, 'encoder': m.encoder, 'row_checks': checks,
            'mismatched_rows': mismatched_rows, 'max_abs_diff': worst, 'failures': failures,
            'full_batch_equals_single': bool(np.array_equal(full.view(np.uint32), single.view(np.uint32))),
            'repeat_equal': bool(np.array_equal(m.forward(feat).view(np.uint32), full.view(np.uint32))),
            'single_sha256': hashlib.sha256(single.tobytes()).hexdigest(), 'seconds': time.time() - t0}
    report['pass'] = all(v['mismatched_rows'] == 0 and v['full_batch_equals_single'] and v['repeat_equal'] for v in report['models'].values())
    import os; report['veclib_threads'] = os.environ.get('VECLIB_MAXIMUM_THREADS')
    with a.out.open('x') as f: json.dump(report, f, indent=2)
    print(json.dumps({k: v for k, v in report.items()}, indent=1))


if __name__ == '__main__': main()
