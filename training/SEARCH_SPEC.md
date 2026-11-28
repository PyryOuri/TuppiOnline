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

Against the plain new network, per deal at 0-0, 1,024 base deals each:

| Search around the new network | Gain |
|---|---|
| The configuration below | **+0.0042 +/- 0.0005** |
| The same with VRPO1 in the play-outs | +0.0026 +/- 0.0005 |
| The same with VRPO1 also scoring the sampled worlds | +0.0014 +/- 0.0006 |
| Heidi 1.2's kind of play-outs (VRPO1, last 6 tricks by the open-card solver), with the rule below | +0.0016 +/- 0.0005 |

Converted with the one direct measurement (+0.0027 per deal = 63% of matches), +0.0042 is roughly
70% of matches against the plain new network. That conversion is linear and rough.

The configuration:

- **Candidates**: the network's own move and its next most probable moves, at most 4 in all, each
  with at least 1% of the network's probability. A decision with one candidate is not searched
  (28% of the unforced decisions).
- **Worlds**: 64 per decision. Play inference as the engine has it (`belief_worlds` in
  `tuppi_env.c`): 4 candidates per world, temperature 2, uniform share 0.5, in card play, scored
  by the **new network** (not VRPO3).
- **Play-outs**: the **new network** on all four seats, to the end of the deal, **no solver tail**.
  Sooli phases by the heuristics, as now.
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

Cost per searched decision: about 180 play-outs of on average 31 network moves with the 768-wide
network, plus scoring 256 candidate worlds; Heidi 1.2 does about 5,200 play-outs of about 11 moves
with the 256-wide network plus 8,192 candidate worlds. By arithmetic the two are of the same order;
it has not been timed natively.

## 3. Cheaper variants, from a recording scored by real outcomes (not yet played as matches)

With the configuration above and fewer worlds, the gain per game was +0.0024 at 8 worlds, +0.0032
at 16, +0.0039 at 32 and +0.0046 at 64. A threshold of 1 standard error in tricks 5-9 and none
from trick 10 (2 before) gave +0.0038 at 8 worlds and +0.0042 at 16.

## 4. Still open

- A small network distilled from the new one, for the play-outs and for scoring the worlds
  (`colab/tuppi_teach.ipynb`, stage B). If it comes close to the new network in those roles the
  search costs a fraction.
- More worlds or more candidates per world (stage C), and teaching the plain network the
  search's decisions (stage A).
- A check on a bank of positions that the hosted implementation chooses as `lookahead.py` does:
  the worlds and per-world values of `lookahead.py` equal the engine's `tc_search_worlds` and
  `tc_search_world_values` exactly (`training/tests/test_lookahead.py`).
