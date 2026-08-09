# Phase 5F results

Phase 5F is a semantics-preserving optimization release for the corrected
Phase 5E multi-observer search. The package version is `0.9.0`. The existing
registered agent IDs and configurations remain unchanged:

- `multi_observer_ismcts_smoke_v1`: 2 simulations;
- `multi_observer_ismcts_small_v1`: 8 simulations;
- `multi_observer_ismcts_standard_v1`: 32 simulations.

All use `redeterminizing_ismcts_v1`, exact Phase 5B uniform hard-feasible
sampling, per-seat information nodes, observer-local re-determinization,
availability-aware UCT, `sqrt(2)`, `match_transition_v1`, bounded `[-1, 1]`
normalization, canonical expansion, frozen `partner_aware_v1` fallback and
showing, and exact-tail disabled. No agent identity was retuned or overwritten.

## Semantic release gate

The preflight suite at the Phase 5E base passed 1,398 tests with 2 skips. The
Phase 5F focused suite passes the indexed-sampler and decision-equivalence
checks. The external semantic corpus gives 36/36 exact serialized diagnostic
matches. Root sampled-world identities, observer-local sampling coordinates,
information-state keys, availability counts, visits, mean utilities, node
counts, re-determinization counts, and selected actions are unchanged.

The independent tiny oracle remains unchanged: PIMC chooses A, the exact
information-set policy chooses B, root-only UCT retains its documented prefix,
and multi-observer search reaches B. The Phase 5E privacy tests still prove
parent-world preservation, acting-hand preservation, legal action mapping,
observation-only policy calls, and no search during showing.

## Strength evaluation

The first valid Phase 5F primary evaluation used a new unsealed development
bank, 32 complementary complete-match pairs from 0–0, natural termination,
fixed agent identities, and 10 deterministic independent worker processes. The
bank is `phase5f_match_v1` with root seed `tuppi-phase5f-match-v1`; it does not
support promotion. The external report is
`/Users/pyryouri/Developer/TuppiRuns/phase5f/evaluation/phase5f_standard_vs_reference_32_pairs.json`,
digest `sha256:371bd37483b483e1c4ee85b2a7c6755ba93929ea8a9dbc769609b5751e82f329`.

`multi_observer_ismcts_standard_v1` versus `development_reference_v1`
(`partner_aware_v1`) produced:

| Pairs | W | T | L | p(win) | 95% interval |
| ---: | ---: | ---: | ---: | ---: | --- |
| 32 | 1 | 6 | 25 | 0.125 | [0.037, 0.213] |

There were no failures or censoring. The Monte Carlo sign-flip result was
approximately `p = 0.0001`. The 10-worker wall time was 1,477.1 s (24.6 min);
an isolated pair calibration took 312.1 s, demonstrating why sequential
execution was unsuitable. Mean deals per complete pair were 20.4 and mean
actions were 1,116. RAMI share was 0.784 and NOLO share 0.216.

The controlled fresh-bank comparison against
`root_info_uct_standard_v1` used 8 complementary pairs. It produced 5 wins,
3 ties, 0 losses (`p(win) = 0.8125`, wide 95% interval [0.266, 0.984]) with no
failures or censoring. This supports the intended structural comparison but is
not a replacement for the 32-pair reference result. Its external artifact is
`/Users/pyryouri/Developer/TuppiRuns/phase5f/evaluation/phase5f_multi_observer_vs_root_uct_8_pairs.json`,
digest `sha256:8d19ace3129fb3e8a4fe70a6559617e3381e798908da72831aa1614dbc59c1602`.

## Decision

The selected gate is **H2 — practical but clearly weaker than the reference**.
The optimization made the first valid evaluation operationally possible and
the multi-observer control strongly improves over root-only UCT, but the
candidate loses clearly to the frozen development reference. The next phase
should test behavioural likelihood/belief weighting and stronger learned or
explicit action models, not add more handcrafted root-tree complexity. Learned
beliefs remain deferred in this phase and no sealed promotion bank was opened.

Archive hashes are unchanged:

- `Archive/tuppi_emulator_v9.py` — `sha256:f5d52f2a41d0c1fc2db18fa54f1171355d432d581c6eb6cb18c1298218aa87c9`;
- `Archive/tuppi_gui_client_multi_v8.py` — `sha256:a926f5a2a7714b82eb7eaa3d4f640ef1676011874cb090712b862c27d63a2558`.

Bulk profiler, semantic, benchmark, and evaluation output remains under
`/Users/pyryouri/Developer/TuppiRuns/phase5f`, outside Git and any synced
folder. The Phase 5F implementation is committed separately from Phase 5E.
