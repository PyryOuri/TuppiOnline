"""Per batch size: which rows' native MLP outputs differ from the full-batch output?"""
import argparse, ctypes as C, json, random, sys
from pathlib import Path
QUAL = Path(__file__).resolve().parent.parent / 'tuppi_speed_qualification_20261014'
sys.path.insert(0, str(QUAL))


def corpus(native, deals):
    rows = []
    for k in range(deals):
        rng = random.Random(f'mlp-invariance|{k}'); deck = list(range(52)); rng.shuffle(deck)
        hands = [sum(1 << c for c in deck[s*13:(s+1)*13]) for s in range(4)]
        cell = k % 25; score = (4*cell, 0) if cell <= 12 else (0, 4*(cell-12))
        d = native.new_deal(hands, k % 4, *score, ruleset=3)
        while d.phase != native.PH_DONE:
            rows.append(native.observe(d, d.cur)); legal = native.legal(d)
            act = native.ACT_SOOLI_ACCEPT if d.phase == native.PH_SOOLI_OFFER and native.ACT_SOOLI_ACCEPT in legal and k % 2 else rng.choice(legal)
            assert native.lib.tc_apply(C.byref(d), act) == 0
    return rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--variant', default='compact128'); ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    from bindings import activate
    candidates, native, best = activate(a.variant)
    import numpy as np
    m = native.Mlp(candidates.loaded(str(best.OPPONENT_ROLLOUT)))
    feat = np.stack([native.encode(o, encoder=m.encoder) for o in corpus(native, 120)])
    N = len(feat); ref = m.forward(feat).view(np.uint32)
    prng = np.random.default_rng(7); per_m = {}
    for M in list(range(1, 260)) + [300, 383, 512, 777, 1024, 2048]:
        bad = rows = 0; pos_bad = set(); maxdiff = 0.0
        for trial in range(6):
            pick = prng.choice(N, size=M, replace=False) if trial else np.arange(M) % N
            out = m.forward(feat[pick])
            b = np.any(out.view(np.uint32) != ref[pick], axis=1)
            bad += int(b.sum()); rows += M; pos_bad.update(np.nonzero(b)[0].tolist())
            if b.any(): maxdiff = max(maxdiff, float(np.max(np.abs(out[b] - ref[pick][b].view(np.float32)))))
        per_m[M] = {'rows': rows, 'mismatched': bad, 'positions': sorted(pos_bad)[:12], 'max_abs_diff': maxdiff}
    # Argmax effect: how often would the masked greedy choice differ between M=1 and the full batch?
    single = np.concatenate([m.forward(feat[i:i+1]) for i in range(N)])
    full = ref.view(np.float32); flips = 0; gaps = []
    import ctypes
    for i in range(N):
        # legal mask from the observation's legal ids (dense action space)
        pass
    report = {'variant': a.variant, 'rows': N, 'per_batch_size': per_m,
              'single_vs_full_max_abs_diff': float(np.max(np.abs(single - full))),
              'single_vs_full_rows_differing': int(np.any(single.view(np.uint32) != ref, axis=1).sum())}
    with a.out.open('x') as f: json.dump(report, f, indent=1)
    clean = [M for M, v in per_m.items() if v['mismatched'] == 0]; dirty = [M for M, v in per_m.items() if v['mismatched']]
    print('rows', N, 'clean M', clean[:20], '... count', len(clean)); print('dirty M', dirty[:60], 'count', len(dirty))
    for M in dirty[:25]: print(M, per_m[M])
    print('single vs full', report['single_vs_full_max_abs_diff'], report['single_vs_full_rows_differing'])


if __name__ == '__main__': main()
