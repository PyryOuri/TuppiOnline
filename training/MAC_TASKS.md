# Decision and tasks for the Mac session (2026-11-28)

Written by the Colab/training session on `claude/colab-pro-compute-eval-nu8in4`. The owner has
decided to stop the research here and to ship what was found; the Mac session runs whatever native
tests it needs and does the implementation. The evidence for every figure is in
`training/README.md`; the search is specified in `training/SEARCH_SPEC.md`.

## Decision

1. **The network.** `vrpo4sym_v1.pt` (768x4, sha256 5322bd22...69a4, on `ai/research/sym-student-20261126`)
   replaces VRPO4 wherever a network makes the final choice: Nelli, and the anchor of the search.
   Plain against plain VRPO4: 62.95% +/- 0.41% of 40,000 complete matches.
2. **The search.** A new controller mode around that network, as `SEARCH_SPEC.md` section 2 states
   it, with the small network `training/models/vrpo4sym_small_v1.pt` (256x2, sha256
   ef2a3365...2210; the new network distilled into VRPO1's shape) in the play-outs and scoring the
   sampled worlds: +0.0036 +/- 0.0005 per deal at 0-0 over the plain new network at 64 worlds,
   +0.0026 +/- 0.0005 at 16 worlds with thresholds 2, 2, 1, 0. It replaces Heidi 1.2's
   configuration; by arithmetic it does about a tenth of her work per decision at 64 worlds.
3. **Not pursued further:** teaching the network the search's decisions (two nulls), a wider
   network, sharper play inference, tuning Heidi 1.2's margins, the scoring table.

One product choice is the owner's: the small network alone is stronger than VRPO4 (below) at an
eighth of the size, so it could also serve as a light Nelli. The recommendation is the large
network for the final choice and the small one inside the search.

## The small network on its own

CPU, 8,192 base deals each, 0-0, sooli tricks by the live rules, the small network's lead per deal:

| Against | Lead |
|---|---|
| VRPO1 (same shape) | +0.00638 +/- 0.00034 |
| VRPO3 | +0.00338 +/- 0.00031 |
| VRPO4 | +0.00196 +/- 0.00030 |
| `vrpo4sym_v1` (its teacher) | -0.00105 +/- 0.00022 |

## Tasks

1. **Artifacts.** Take `vrpo4sym_small_v1.pt` from this branch and check both hashes. Produce the
   release formats of both networks (lite `.npz`, compact `.f32`) with the existing exporters and
   the conversion check used for `vrpo4sym_v1`.
2. **Complete matches, natively** (replacing the checks the Colab session did not run): the small
   network against VRPO4 and against `vrpo4sym_v1`, plain, a few thousand mirrored pairs each.
   Expected from the deal-level figures: about 59% and about 45%. A clear miss means the
   conversion or the harness differs; stop and report.
3. **The controller.** In `ai/native/tuppi_browser.c` add a mode with `SEARCH_SPEC.md` section 2:
   - candidates: the anchor's greedy move, then its next most probable legal moves by softmax of
     its logits over the legal actions; at most 4 in all, each with probability at least 0.01;
     one candidate means no search;
   - worlds and values: `tc_search_world_values` with 64 worlds, `dd_left` 0, the small network
     as the play-out model; play inference by `tc_env_set_belief(env, small, 4, 2.0, 0.5, 1)`
     (card play, no soolaaja, as `belief_applies` has it); showing fix on;
   - rule: per candidate j other than the anchor, d[w] = value[w][j] - value[w][anchor] over the
     64 worlds; mean, standard deviation with n - 1, se = sd / sqrt(64); eligible if mean > 0.003
     and mean > 2 se; play the eligible candidate with the largest mean, else the anchor. The
     same for bids and card play. Repeated worlds count as worlds.
   - sooli phases: the heuristics, as in the lite modes.
   A cheaper variant for later: 16 worlds, the factor 2 replaced by 2, 2, 1, 0 for bids, tricks
   1-4, 5-9 and 10-13.
4. **Check against the reference bank.** `training/reference/search_bank_v1/part_0000.npz` holds
   3,913 decisions of that configuration (float32 on a CPU): `state` (the `TcDeal` record as
   bytes), `seed`, `cand` and `k` (the candidates, anchor first), `q` (every world's value of
   every candidate, the acting team's sign), `mean_gain`, `se`, `spec_choice`. For a state, the
   observation of `state.cur`, an rng set to `seed` and the calls of task 3 give the worlds the
   bank used (`tc_search_worlds` draws them: `training/tests/test_lookahead.py` shows the
   equality, with and without play inference). For the 3,564 card-play decisions (`phase` > 0)
   the values do not depend on any further draw, so candidates, means and choice should agree up
   to floating point; a resampled world can differ where two likelihoods are equal to the last
   bit. Report the share of decisions with the same candidates and the same choice; anything
   under 99% on card play needs an explanation. Bids involve sooli draws in the play-outs and
   agree only statistically.
5. **Strength, natively, short.** The new mode against Nelli on `vrpo4sym_v1`, mirrored complete
   matches or duplicate deals at 0-0. Expected: about +0.0036 per deal at 0-0, roughly two thirds
   of matches. The search is cheap enough that a few thousand deals should not tie the Mac up;
   time it per decision and record it, since the cost figures in `SEARCH_SPEC.md` are arithmetic.
6. **Release work** as the project does it: models.json roles (anchor `vrpo4sym_v1`, play-outs
   and likelihood the small network), hosted checks, qualification.

## What the training code offers for these tasks

- `python -m tuppi_train.matches --a <net> --b <net> --pairs N`: complete matches of plain
  networks in mirrored pairs (CPU works; the GPU is faster).
- `python -m tuppi_train.lookahead ...`: the reference implementation of the search; `--help`
  lists the options of `SEARCH_SPEC.md` (`--rollout`, `--belief 4`, `--all-worlds`, `--worlds`).
- `python -m tuppi_train.calibrate record --bank ...`: more reference decisions, any size.
- `sh training/build_train.sh` builds the library these need; nothing under `ai/`, `engine/`,
  `web/` is touched by this branch (`training/tests/test_hosted.py`).
