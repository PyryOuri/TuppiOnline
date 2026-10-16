# C5 contract report — actual-root information-consistent three-card option

Tasks C5.01 and C5.02. Date 2026-09-26. **Status: CONTRACT_PASS for both.
The P.C5 screen is gated and was not run. No strength claim.**

## Implementation (`tuppi_ai/research/c5_option.py`)

- **Eligibility.** The real actor is about to lead an ordinary trick with ten tricks complete, every seat holds three cards, and there are at least two legal leads. Two-card states are not eligible.
- **Support.** The complete hard-feasible support under the native constraint law (capacities, proven voids, unplayed shown cards with their shower). It is **counted before it is enumerated** and capped at 100 worlds; a support above the cap is `TOO_LARGE` with no partial set. The strict engine model (`tuppi_exact.constraints.derive_show_exclusions`) must give the same set, otherwise `CONSTRAINT_MODEL_MISMATCH` and fallback.
- **Model.** The three other seats, partner included, are the deterministic native clone, each from its own projected observation, with ascending-id ties. The prior is uniform over the complete support. Utility is the frozen float32 equity change in the root's sign.
- **Optimiser.** Q(a) = Σ_o mass(o) · max_b E[U | o, b], with **one b per root information group** (`optimise_groups`); a within-group mismatch raises `KeyCollision`. The root's engine legal order is the declared tie order.
- **Deployed option (`C5Agent`).** Plays the chosen lead and stores the key → b map for the deal. At the next root decision it plays the stored b. It falls back to the base policy, recording the reason, on an unexpected key, a support or model failure, a node cap or a deadline. Forced calls are played without a lookup. At most one option per deal.

## Acceptance tests (`tests/research/test_c5.py`, 8 tests)

| ID | Result |
|---|---|
| O01 | PASS. F05's 18-world support matches the independent `fixtures.support_worlds` enumerator. A cap one below the count gives `TOO_LARGE` with no worlds. An injected strict exclusion gives `CONSTRAINT_MODEL_MISMATCH`. F05 has no verbal show, so strict and native agree. |
| O02 | PASS. At an ordinary RAMI three-card boundary after two sooli declines (F03's deck), reconstructed worlds keep ruleset 3, both declines and the contract. Each clone seat's projected observation holds only its own hand. The declines are part of the option's scope. |
| O03 | PASS. Indistinguishable worlds with opposite best replies share one compromise b; a distinguishable companion allows different b. Both agree with an independent brute-force enumeration of key → action maps. |
| O04 | PASS. A non-uniform posterior changes the choice. Different legal sets under one key, and a deliberately lossy key function on F05, both raise `KeyCollision`. |
| O05 | PASS on F05. Complete option ≥ the W128 comparator and ≥ an "always lowest card" policy in the same model; old lead + optimised future option ≥ W128; root-only clairvoyance ≥ option. |
| O06 | PASS. Every action-minus-optimum gap is ≤ 0, and real negative gaps exist on F05 (leads 33 and 34 against 30). The optimum-minus-feasible gap is never negative. |
| O07 | PASS. The W128 comparator's later decisions each start from a NativeFork of the same post-lead snapshot; all forks' snapshots are identical. |
| O08 | PASS. Replaying F05's real deal, the option starts, is followed at the next root decision and the last card is forced: no fallback, because the real world lies in the support under the same clone model. An emptied plan gives an "unexpected information key" fallback; `node_cap=5` gives a node-cap fallback with no option stored. |
| O09 | PASS. Every group has at most two later choices, at least one real two-way choice exists, and `NativeModel.finish` raises on any root choice beyond the horizon (none occurred). Two-card states are not eligible. |
| O10 | PASS. One option per deal; the log records support size, nodes, wall time, Q values and the choice. |

## F05 numbers (`logs/c5_diagnostics.json`)

| | Value |
|---|---|
| Support | 18 worlds (unconstrained ceiling 1,680) |
| Q per lead | 30: −0.029364 (chosen), 33: −0.029588, 34: −0.029588 |
| Root-only clairvoyant bound | −0.028911 |
| Work | 1,017 model nodes, 21 ms wall |

These values are under the fixed-clone model on one fixture position. An option that is optimal against clone continuations may lose against searching players; that would be model mismatch, not a contradiction.

## Next gated step (P.C5, not authorised)

1. Collect eligible positions (the spec suggests 64) under a declared public gate, counting every source deal and gate failure.
2. Measure coverage (support ≤ cap, strict/native agreement), latency with a reserved baseline-fallback budget, and the per-option equity against the full W128 comparator.
3. Then evaluate against actual searching teammates and opponents in fresh whole deals.
