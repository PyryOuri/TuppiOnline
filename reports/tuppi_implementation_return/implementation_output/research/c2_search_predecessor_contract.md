# C2.02 — searching-predecessor lifecycle extension (contract only)

Date 2026-09-26. **Status: CONTRACT_PASS for the modelling mechanics. No claim of literal cancellation.**

## What is modelled

`tuppi_ai/research/c2_blind_bids.py::SearchPredecessor` gives each earlier seat's bid in a joint layout as the choice of a **NativeFork of that seat's live controller**, asked on the predecessor's own engine observation.

- The observation is rebuilt by replaying placeholder earlier NOLO bids. It is byte-identical to the native pre-commit observation (test B02 of `test_c2.py`), and contains no bid content and no focal hand.
- The live agent is never called: `test_B07_modelled_queries_never_touch_*` checks its snapshot and its empty call history.
- The cache key is (observation bytes, live controller snapshot id, legal order, configuration id).
- Each cache entry stores the fork's post-call snapshot. A cache hit returns the same bid, and a fresh fork re-deriving it reaches exactly that snapshot (`test_B07_a_cache_hit_*`). A cached literal call therefore stands for its full state advancement, and the test also shows the advancement is real (the snapshot differs from the live one).
- Hypothetical hands use ascending card order, so the engine tie order follows it; this is a declared model choice.

## What is NOT claimed (the gate)

The identity `Q(a) − Q(b) = E[1(E)(U_a − U_b)]` assumes a fixed simultaneous model in which unused calls have no state effects. The literal v3 process is different:

1. Only **reached** seats are ever called (the server's `_resolve_locked_showing`), and
2. each real call advances that seat's controller (scalar RNG; settings unchanged at a v3 bid), so its later decisions in the deal can change.

The fork model computes a *reach model*. It does not reproduce the live call schedule or the downstream state effects of the calls it models. A reach-model improvement and a full-policy improvement must be reported separately, and a full-game evaluation keeps the as-is call-suppression process untouched. None of this was run: P.C2 is gated.

## Before P.C2 needs

- Calibrate predecessor pass rates and chosen cards of the clone model (C2.01) against these search forks, by reveal seat and score, with denominators.
- Measure unconditional reach frequencies, per-cluster variance and CPU. The W128 bid searches cost 2–6 s CPU each (`builds/parity_B0-source.json`), and forks multiply that per layout.
- Then run natural v3 games against named searching opponents, preserving score and reveal-position strata.

## Tests (`tests/research/test_c2_search.py`, W8 searching predecessors, 2 layouts)

| ID | Test | Result |
|---|---|---|
| B07 | `test_B07_modelled_queries_never_touch_the_live_predecessors`, `test_B07_a_cache_hit_reproduces_*` | PASS |
| B02 | `test_B02_predecessor_bids_are_computed_once_and_reused_*` | PASS (a second focal action set runs entirely on cache hits) |
| B06, B08 | `test_B06_B08_ablations_and_units_*` | PASS |
