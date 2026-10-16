"""How often does the one-row kernel's rounding change the rollout's masked argmax?"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mlp_batch_profile import corpus, QUAL
sys.path.insert(0, str(QUAL))
from bindings import activate
candidates, native, best = activate('compact128')
import numpy as np
m = native.Mlp(candidates.loaded(str(best.OPPONENT_ROLLOUT)))
obs = corpus(native, 600)
feat = np.stack([native.encode(o, encoder=m.encoder) for o in obs])
full = m.forward(feat); single = np.concatenate([m.forward(feat[i:i+1]) for i in range(len(feat))])
flips = multi = 0; gaps = []; diffs = []
for i, o in enumerate(obs):
    ids = native.legal_obs(o)
    if len(ids) < 2 or max(ids) >= full.shape[1]: continue
    multi += 1
    a, b = full[i, ids], single[i, ids]
    if ids[int(np.argmax(a))] != ids[int(np.argmax(b))]: flips += 1
    s = np.sort(a); gaps.append(float(s[-1] - s[-2])); diffs.append(float(np.max(np.abs(a - b))))
gaps = np.array(gaps); diffs = np.array(diffs)
r = {'rows': len(obs), 'rows_with_choice': multi, 'argmax_flips_single_vs_batch': flips,
     'max_abs_q_diff': float(diffs.max()), 'median_abs_q_diff': float(np.median(diffs)),
     'top2_gap_quantiles': {q: float(np.quantile(gaps, q)) for q in (0.001, 0.01, 0.05, 0.5)},
     'share_gap_below_max_diff': float(np.mean(gaps < diffs.max())), 'share_gap_exactly_zero': float(np.mean(gaps == 0))}
Path('results/mlp_argmax_flips.json').write_text(json.dumps(r, indent=1)); print(json.dumps(r, indent=1))
