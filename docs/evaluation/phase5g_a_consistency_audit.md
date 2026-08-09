# Phase 5G-A consistency audit

Phase 5G-A audits the apparent conflict between the Phase 5D-C root-UCT result
(`0/0/32` against the development reference) and the Phase 5F control result
(`5/3/0`). It does not add or retune an agent, and it does not introduce a
belief model.

## Exact matchup resolution

The Phase 5F artifact
`phase5f_multi_observer_vs_root_uct_8_pairs.json` identifies the candidate
profile as `multi_observer_ismcts_standard_v1` and the opponent profile as
`root_info_uct_standard_v1`. Its purpose is the observer-re-determinization
control. It is not a root-UCT-versus-reference comparison.

The Phase 5D-C artifact
`standard_reference_32pairs.json` identifies the candidate as
`root_info_uct_standard_v1` and the opponent as `partner_aware_v1`, the exact
canonical target of `development_reference_v1`.

The agent identities resolve as follows:

| Role | Agent ID |
| --- | --- |
| `root_info_uct_standard_v1` | `agent:sha256:6f050d525fec19ec73787172905b2af50fd3fe48c4eed2a0a7ba0da2e90e77c2` |
| `multi_observer_ismcts_standard_v1` | `agent:sha256:5266a66b09b9489c0b97dc277d6a92d54079032e90087624d25f867ff1c02fcb` |
| `development_reference_v1` / `partner_aware_v1` | `agent:sha256:d8b426f1263c7ce32bdef82e4971dc2e494950f155e15db9b69fc6334a2ac929` |

The root-UCT configuration is unchanged: eight simulations, frozen
`partner_aware_v1` showing and rollout, `sqrt(2)`, `match_transition_v1`,
bounded identity normalization, canonical expansion, exact-tail off, and the
existing deterministic seed protocol. The current root registry digest is
`sha256:853ce7a1f8fc6957ec54f0f18d20870a437b3a8d256c5b500bd64c894330094e`.

## Independent reconstruction

The retained historical JSON reports contain aggregate summaries only; they do
not contain pair-level `PairRecord` data. The audit therefore replayed the
frozen deterministic work units and wrote privacy-safe raw pair records outside
the repository:

- `/Users/pyryouri/Developer/TuppiRuns/phase5g-a/replay_phase5d_c_root_vs_reference.json`
- `/Users/pyryouri/Developer/TuppiRuns/phase5g-a/replay_phase5f_control_bank_root_vs_reference.json`
- `/Users/pyryouri/Developer/TuppiRuns/phase5g-a/replay_phase5f_original_control_multi_vs_root.json`

The Phase 5D-C replay used the original `phase5d_b_match_v1` stream bank,
`tuppi-phase5d-b-match-v1`, initial dealer 0, 32 pairs, and safety cap 96. It
reproduced the retained report exactly:

| Pairs | W | T | L | p(win) | mean `D_match` |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 0 | 0 | 32 | 0.000 | -1.000 |

All pairs completed; failures and censoring were zero. The reconstructed
confidence fields, sign-flip result, pair outcomes, and length distribution
match the historical aggregate byte-for-value where deterministic.

The same frozen root-UCT/reference comparison on the Phase 5F control bank
(`phase5f_root_uct_control_v1`, root seed
`tuppi-phase5f-root-uct-control-v1`, initial dealer 0, eight pairs, cap 704)
was `0/0/8`, with p(win) 0.000 and no failures or censoring. This is a
cross-bank descriptive check, not a pooled estimate.

The original Phase 5F multi-observer/root-UCT control replay reproduces its
reported `5/3/0`, p(win) 0.8125 result under the same orientation and pair-level
formula. Thus the 5/3/0 result is not a sign inversion of the 0/32 result; it is
the expected result of a different candidate and a different opponent.

## Orientation and evaluator checks

The evaluator uses the frozen pair-level definition

```text
D_match = (Y_E - Y_O) / 2
p_candidate = (1 + mean(D_match)) / 2
```

where `Y` is the even-partnership result in each complementary leg. Synthetic
fixtures cover candidate wins both legs, loses both legs, one leg each,
candidate on the even partnership in Leg E, and candidate on the odd
partnership in Leg O. They also cover W/T/L classification, p(win), and report
field reconstruction. Censoring is excluded from the primary endpoint rather
than converted into a tie.

The evaluator remains `tuppi.match.pair_inference.v1`; the match protocol is
`tuppi.match.complete_duplicate_pair.v1`; the stream protocol is
`tuppi.match.stream.v1`; starts are 0–0 and termination is natural. Worker count,
elapsed time, output path, and timestamps are operational and excluded from
semantic manifest comparisons.

The Phase 5F primary multi-observer/reference result (`1/6/25`, p(win) 0.125)
also uses the same evaluator and is independently checked by replaying its
separate control work unit. No orientation or scoring defect was found.

## Manifest and dealer findings

The two apparent results are not semantically compatible manifests:

| Field | Phase 5D-C result | Phase 5F control |
| --- | --- | --- |
| Candidate | root-only UCT, 8 simulations | multi-observer search, 32 simulations |
| Opponent | `partner_aware_v1` / development reference | root-only UCT, 8 simulations |
| Bank | `phase5d_b_match_v1`, 32 streams | `phase5f_root_uct_control_v1`, 8 streams |
| Initial dealer | 0 | 0 |
| Safety cap | 96 | 704 |
| Comparison purpose | strength versus reference | observer-modelling control |

Both historical banks start all streams at dealer 0, so an initial-dealer
effect cannot explain their different matchups. The audit does not retrospectively
reweight either result and does not invent a dealer-stratified estimate from
single-dealer banks. Future development banks should distribute initial dealer
across independent stream roots when the protocol supports that without
changing the frozen historical work units.

The root-UCT/reference cross-bank replay was negative on both banks (`0/0/32`
and `0/0/8`). Because the apparent contradiction is proven to be a different
matchup rather than an unresolved same-agent bank discrepancy, no new 32-pair
audit bank was opened in this phase. The sealed promotion bank remains
untouched.

## Integrity classification

This phase selects **I4 — manifest/comparison mismatch**. The frozen agents did
not drift, and the evaluator did not invert the result. The Phase 5F control was
correctly executed but was incorrectly treated as if it were root-UCT versus
the development reference. The true historical conclusions remain:

- root-only UCT is a negative baseline against `development_reference_v1`;
- multi-observer search improves over root-only UCT in the dedicated control;
- multi-observer search remains clearly below the development reference in the
  separate 32-pair result.

Phase 5G-B may introduce behavioral belief modelling only after this corrected
comparison identity is carried forward. No historical report is overwritten.

Archive hashes remain unchanged:

- `Archive/tuppi_emulator_v9.py` — `sha256:f5d52f2a41d0c1fc2db18fa54f1171355d432d581c6eb6cb18c1298218aa87c9`;
- `Archive/tuppi_gui_client_multi_v8.py` — `sha256:a926f5a2a7714b82eb7eaa3d4f640ef1676011874cb090712b862c27d63a2558`.
