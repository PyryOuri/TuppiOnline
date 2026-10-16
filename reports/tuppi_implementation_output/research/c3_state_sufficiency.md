# C3a state-sufficiency report — proposed `C3-marginal-RNG-mode-model-v1`

Task C3a.01 output. Date 2026-09-26. **Contract status: solver and sufficiency
evidence pass. The model itself is a proposed idealisation, not validated;
P.C3a (row sampling, direct-match validation) is gated and was not run.**

## 1. The question

Can match value under the pinned default factory (`best_agents`, W128) be
computed from a finite Markov state? The literal B0 process cannot: its
future depends on each seat's persistent scalar PRNG and its native sooli
settings (E002/E004). The spec proposes an augmented state
`(score, dealer, mode per seat)` under an **independent-randomness**
idealisation. This report records what establishes that state and what
remains an assumption.

## 2. Decision-relevant mutable state of one best seat (from the source)

| Field | Read by decisions? | Evidence |
|---|---|---|
| `Searcher.rng` (scalar SplitMix) | yes (root sampling, sooli draws) | search.py `action_values`; tuppi_env.c `search_core`. **Replaced by independent randomness in the model.** |
| `Searcher.np_rng` | no for best (belief 0, no opp_temp, native loop) | search.py: used only by the Python loop and belief paths |
| native env sooli settings (belief, return_pi, play_heur, λ) | yes, see §3 | tuppi_env.c `resolve_sooli`, `search_core` |
| env slot deal states | no (overwritten before every use) | `sample_root_worlds` loads every used slot |
| env slot RNGs, `deals_in_match` | no (read only by `new_match`/`deal_random`, never on the search path) | tuppi_env.c; snapshots carry a slot digest (A07) |
| encoder, equity table, single_deal | constant after construction | best.py, search.py |
| `last_values`, scratch arrays | diagnostics/scratch | search.py |
| rollout chunk (process global) | no effect on values in tested cases | chunk 32 vs 128 bitwise equal on two network-using cases (builds/r0_api_v1) |
| DD solver thread-local caches | exact bounds, value-neutral if the solver is correct | tuppi_dd.c header; not re-probed |
| `show_searcher` | absent (`show_worlds` is None) | best.py |

## 3. The sooli-setting modes

**Setter inventory** (`test_K05_setter_inventory_is_complete` fails if a new one appears):
- Live search path: `search.py` offer → **O** = (17, 0, 1, 0.3); searched give/return/play → **P** = (17, 0, 0, 0.3); the v2-only ordinary path → O (not reached under v3).
- Construction: `tc_env_new` calloc → **C** = (0, 0, 0, 0).
- Not the live agent: `review.py` (its own environment), `rule_bidder.py` (parked T5 experiment), and tools (`gen_game_db`, `sooli_play_eval`, `sooli_bank`).

**Transitions.**
- A searched offer leads to O.
- A searched give or play leads to P.
- Forced calls, the heuristic return and v3 ordinary/bid calls leave the mode unchanged.
- C is never re-entered.

The tracker's deductions were compared call by call with the research build's actual native configuration over a complete search-played sooli deal: cold → offer → give → forced and unforced plays → heuristic return (`test_A06_sequence_covers_…`). They agree on every call.

**Reduction C ≡ P (deduced, then tested).** belief and λ are read only by root sampling in a sooli phase (`tc_sample_world_sooli` applies only when a soolaaja exists), and the agent re-sets both immediately before every such search. Inside rollouts only `return_pi` (0 in every mode) and `play_heur` matter. So C and P differ in no field any decision reads, and only bid searches (whose rollouts reach sooli) see O versus not-O.
`test_K05_cold_and_play_modes_are_equivalent_…` finds C and P bitwise equal on a v3 bid search whose rollouts resolved soolis, and O different. The per-seat mode therefore reduces to `play_heur ∈ {0, 1}`: **100 × 2⁴ = 1,600 nominal states** instead of 8,100. This is tested evidence on one position plus a source argument, not a theorem.

## 4. What is idealised, and what would falsify it

1. **Independent randomness.** The model treats each decision's search randomness as fresh. B0's scalar RNG is a deterministic function of its seed and call history, so the model is not B0's finite-seed machine and it is named differently (`MODEL_ID` ≠ `LITERAL_B0_ID`).
2. **Stationarity.** Transition laws may depend only on (score, dealer, modes). Anything else carried between deals (none found in §2) would break sufficiency.
3. **Initial state.** Fresh matches start with every seat in C (≡ P). No stationary mode distribution is assumed.
4. **Falsification:** direct complete v3 matches with fresh B0 agents disagree with the kernel prediction beyond a declared tolerance, or a new setter or field is found. `direct_match_agreement` treats wide overlapping intervals as unresolved, not as agreement.

## 5. Solver (`tuppi_ai/research/c3_kernel.py`) — tested

- Sparse rows; dense direct solve with residual and condition number; lower/upper value iteration with a non-contraction check; exact rational elimination; Monte Carlo simulation; paired difference `vC − vB = (I−PC)⁻¹[(rC−rB) + (PC−PB)vB]` (K06).
- The 100-state score × dealer chain built from the stored `DealModel` reproduces `equity_incumbent.json`'s table on every state to 1e-10, including resets and overshoot absorption (K06).
- Unobserved rows, rows summing above 1 and closed non-absorbing classes raise `Unresolved`: nothing is smoothed, clipped or given pseudocounts (K07).
- Bundle bootstrap resamples whole deck bundles, and the numerical residual is reported separately from the sampling interval (K08).

## 6. Next gated step (P.C3a, not authorised)

1. Sample rows for the reduced model: fresh B0 agents forked at declared (score, dealer, mode) states.
2. Estimate the kernel with bundle bookkeeping.
3. Screen the state count and cost per row, and project precision per CPU second against direct complete-match pairs (target: equal match-win precision at ≤ half the direct-match CPU).
4. Validate against independent direct v3 match pairs at a pre-declared tolerance.

This needs an approved manifest with numeric caps. If the model fails the tolerance, it is reported as rejected; C1, C2, C3b, C4 and C5 do not depend on it.
