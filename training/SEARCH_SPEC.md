# The strongest configuration measured so far (2026-11-28)

For whoever changes the hosted bots. Everything here was measured with `training/tuppi_train`
on a Colab L4 (records and tables: `training/README.md`); nothing was confirmed natively, by the
owner's decision. "New network" is the baked suit-symmetric network (`vrpo4sym_v1.pt` on the
branch `ai/research/sym-student-20261126`, `best_student.pt` of `sym_preflight_v1` on Drive).

## 1. The network (no code change)

Plain new network against plain VRPO4: 62.95% +/- 0.41% of 40,000 complete matches; +0.0027 per
deal at 0-0, +0.0072 at the release evaluator's uniform scores. The Mac measured Nelli on it at
62.4% of matches against Nelli 1.1. Use it wherever a network makes the final choice.

## 2. The search (a change of the controller in `ai/native/tuppi_browser.c`)

Against the plain new network, per deal at 0-0, 1,024 base deals each. "Small network": the new
network distilled into VRPO1's shape (256 wide, 2 blocks), `runs/teach_v1/small_net/best_student.pt`
on Drive.

| Search around the new network | Sampled deals | Gain |
|---|---|---|
| New network in the play-outs and scoring the deals | 64 | **+0.0042 +/- 0.0005** |
| **Small network in both roles (recommended)** | 64 | **+0.0036 +/- 0.0005** |
| Small network in both roles, thresholds 2, 2, 1, 0 by phase | 16 | +0.0026 +/- 0.0005 |
| VRPO1 in both roles | 64 | +0.0014 +/- 0.0006 |
| Heidi 1.2's kind of play-outs (VRPO1, last 6 tricks by the open-card solver) | 64 | +0.0016 +/- 0.0005 |

Converted with the one direct measurement (+0.0027 per deal = 63% of matches), +0.0036 is roughly
67% of matches against the plain new network and +0.0042 roughly 70%. That conversion is linear
and rough.

The configuration:

- **Candidates**: the network's own move and its next most probable moves, at most 4 in all, each
  with at least 1% of the network's probability. A decision with one candidate is not searched
  (28% of the unforced decisions).
- **Worlds**: 64 per decision. Play inference as the engine has it (`belief_worlds` in
  `tuppi_env.c`): 4 candidates per world, temperature 2, uniform share 0.5, in card play, scored
  by the **small network** (not VRPO3; the new network itself is no better in this role).
- **Play-outs**: the **small network** on all four seats, to the end of the deal, **no solver
  tail**. Sooli phases by the heuristics, as now. (The new network itself in the play-outs is
  worth a further 0.0006 +/- 0.0005 at about 8 times the network cost.)
- **Rule**: with the mean gain of a candidate over the network's move across the 64 worlds and
  its paired standard error (every world counted, repeated ones too), play the candidate with the
  largest mean gain among those above 0.003 and above 2 standard errors; otherwise the network's
  move. Bids and card play alike.

What differs from Heidi 1.2: she considers every legal move, 1,024 worlds, takes the best mean with
a margin (0.003 in card play, 0.03 for bids) and no standard-error test, scores worlds with VRPO3,
plays out with VRPO1 and solves the last 6 tricks. With her kind of model (biased: real gains
follow its gains with a slope of 0.35) a margin rule without the test is worth about half of the
tested rule; whether swapping only her anchor helps has not been measured and the repository
records an earlier anchor swap as neutral.

Cost per searched decision, by arithmetic (not timed natively): about 180 play-outs of on average
31 moves and 256 candidate worlds to score, all with a network of VRPO1's size. Heidi 1.2 does
about 5,200 play-outs of about 11 moves with VRPO1, the solver, and 8,192 candidate worlds scored
with the four times larger VRPO3. That is an order of magnitude less work than Heidi 1.2 at 64
deals, and several times less again at 16; and 28% of the unforced decisions are not searched at
all.

## 3. Fewer or more deals

Played: 16 deals with thresholds of 2, 2, 1 and 0 standard errors in the four phases (bids, tricks
1-4, 5-9, 10-13) keep +0.0026 of the +0.0036. From recordings scored by real outcomes, with the new
network in both roles: +0.0024 per game at 8 deals, +0.0032 at 16, +0.0039 at 32, +0.0046 at 64
and +0.0056 at 256.

## 4. Tried and closed

- Teaching the plain network the search's decisions (1.2 million labelled decisions): no gain,
  49.5% +/- 0.5% of matches against the original. Likewise an earlier trial on single play-outs.
- A looser rule for Heidi's kind of model, a solver tail, sharper play inference (CPU pilot):
  no gain.

## 5. Still open

- Whether swapping only Heidi 1.2's anchor helps under her own rule: not measured.
- A check on a bank of positions that the hosted implementation chooses as `lookahead.py` does:
  the worlds and per-world values of `lookahead.py` equal the engine's `tc_search_worlds` and
  `tc_search_world_values` exactly (`training/tests/test_lookahead.py`).
- More candidates per world (cheap; the recording was not finished).
