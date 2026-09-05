# N01 — Make the evidence independently reproducible

Status: READY. Read BACKGROUND.md, fixtures.json, preparation.json, and the
reproduction appendix of framing 1. Do not rediscover a framing or tune a policy.

## Outputs and steps

1. Create `src/tuppi_nolo/__init__.py` declaring the research boundary, and
   `src/tuppi_nolo/fixtures.py`, a small loader for the supplied JSON format.
   Validate schema version, 52 unique cards, 13 per hand, dealer and prefixes.
   Preserve hand order. Use the ordinary engine for shows and plays.
2. Add `tests/nolo/test_evidence.py`. Test the acting observation, expected bot
   action, hard-support counts and actual-layout solver values for A/B/C.
   The research harness may hold a private DealState; policy-facing objects may
   hold only PlayerObservation.
3. Port the framing's exhaustive reproducer into an independent test helper.
   Enumerate all unconstrained partitions, not a sample or only the dealt hand.
   Compare accepted assignment **sets**, not just their sizes, with enumeration
   of the hard model. Reproduce A/B all-path counts in fixtures.json and C's
   minimax-pair table in BACKGROUND.md. Keep the all-path enumerator independent
   of the later optimized verifier/search.
4. Add `docs/nolo/results/N01.md`, including the three input corrections:
   avoidable wins do not imply no lower card; losing margins can matter; only
   down-team winning margins are always erased. Link authoritative functions
   and the counterexample. Do not edit the charter/game object/framing.

## Acceptance endpoints

| Check | Exact target |
| --- | --- |
| A replay | Seat 2, trick 10/position 1, bot `QD`, support 20 of 560 |
| B replay | Seat 0, trick 10/position 3, bot `3C`, support 2 of 90 |
| C replay | Seat 2, trick 10/position 3, bot `KC`, support 24 of 90 |
| A universal escape | `8S` gives `{7:1680}`; `QD` gives `{7:360,8:360,9:480}` |
| B correct line | `9C → 3C` gives `{4:16}` across both worlds |
| B negative control | `9C → 3H` gives `{6:8}`, and must fail a claimed at-most-4 guarantee |
| C negative control | Five minimax-pair counts match BACKGROUND; no universal `10D` claim |
| Corrupted input | Duplicate/missing card or illegal prefix is rejected explicitly |

Run `python -B -m pytest -q tests/nolo/test_evidence.py` with the shared interpreter.
Exhaustive tests may be marked slow with a documented explicit invocation, but
must actually be run for task completion. A source-hash change is a drift signal,
not permission to update expected answers. If expectations fail, preserve the
position and report FAILED_CHECK. N02 starts only after the baseline is explained
and the reproduced evidence passes.
