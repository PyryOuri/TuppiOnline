# Acceptance tests and stop conditions

These are required tests to implement in the directory workspace. They are NOT reported game-test results. The included `reference_math.py` is a small independent mathematical reference, not a Tuppi emulator. Map real tests to these stable IDs in IMPLEMENTATION_REPORT.md.

## C0 identity, containment and lifecycle

| ID | Required test | Failure meaning |
|---|---|---|
| A01 | Record exact source paths/hashes and loaded library/model/equity/encoder; importing ENGINE resolves to the v3 checkout. | Wrong runtime or unidentified baseline; stop empirical claims. |
| A02 | Installed, source and research builds have separate ownership domains; deliberately crossing Env/Mlp library IDs is rejected. | Unsafe native ABI boundary. |
| A03 | Disabled research path versus unmodified-source selected actions, values, error status and scalar RNG on fixed cases. | Instrumentation changed the comparator. |
| A04 | Native struct sizes/offsets/endian and action ranges agree with Python; malformed dimensions/overflow reject. | Do not load native records or run search. |
| A05 | Full legal observation wire round-trip preserves ordered hands/actions, v3 ruleset, bid masking, offers and private exchanges. | Replay is not established. |
| A06 | ReplayFork reproduces an entire own-observation call sequence, including cold, offer, give/play, forced and heuristic branches. | Cannot claim a complete baseline-policy comparison. |
| A07 | NativeFork export/import matches ReplayFork and fork mutations do not alter the source environment. | Fork implementation invalid. NativeFork may remain unimplemented if ReplayFork suffices. |
| A08 | Changing other hands/hidden bids at fixed complete actor input and seed leaves features and policy action unchanged. | Information leakage. |
| A09 | Different worker counts/task orders leave independent-bundle results unchanged; no cross-bundle reused controller state. | Cluster independence/reproducibility failure. |
| A10 | Snapshot fields exclude true hidden hands from policy input; diagnostic queries do not advance real policy state. | Counterfactual contamination. |
| A11 | Controller state is retained through all deals of a match leg; cold-reset and retained-state instruments are distinct. | Wrong complete-match estimand. |
| A12 | Protected files/banks/live paths unchanged after tests; audit source drift identified rather than reset. | Scope violation; halt writes. |

## Fixtures and v3 runner

| ID | Required test | Failure meaning |
|---|---|---|
| F01 | Validated blind-bid fixture, both reached/unreached latent cases and forehand E=1 control. | No valid C2 integration fixture. |
| F02 | Reachable NOLO discard with unequal capacities, nonconstant proxy and multiple same-suit shows companion. | Proxy test may be vacuous. |
| F03 | Accepted pre-give sooli fixture generated through legal v3 transitions; forced acceptance labelled synthetic. | Wrong accepted-population data. |
| F04 | Receiver14-card hand, 13 legal returns excluding g; private own hand and exchange masks correct. | Illegal learned exchange policy. |
| F05 | Ordinary three-card boundary with complete support>=2 and non-forced future response; ruleset preserved. | No meaningful C5 case. |
| F06 | Score48 both winners, multiple margins, reset, zero-score award and overshoot; uncertain-winner companion. | Unsafe stopping or wrong scoring. |
| R01 | v3 runner handles NOLO, ordinary RAMI after declines, first/second sooli accept, give/return and immediate solo failure. | Incomplete game runner. |
| R02 | Eight rotated/assigned games retain one base-deck cluster; arbitrary search opponents accepted. | Wrong pairing/comparator. |
| R03 | Full-match deck streams indexed correctly, dealer rotation correct, complementary seeds explicit. | Match comparison not reproducible. |
| R04 | Deliberate action failure/time cap remains in ledger; unresolved matches are not silently scored draws. | Biased failure handling. |
| R05 | Score-distribution weights retained; legacy uniform label distinguished from uniform25states. | Wrong population. |
| R06 | A fixed identical-policy comparison is analysed statistically; code does not force 0.5 because of a symmetry assumption. | A false self-play identity can conceal bugs. |

## C1 control variates

| ID | Required test | Failure meaning |
|---|---|---|
| V01 | Per-layout proxy agrees with independent contested-round enumeration, both team signs, removed-card semantics. | Wrong proxy definition. |
| V02 | Proxy varies across at least two worlds/actions; an observation-constant proxy gives no variance gain. | Vacuous test/control variate. |
| V03 | Exact finite distribution verifies unbiased correction with deliberately wrong/reversed proxy and fixed beta. | Estimator bias. |
| V04 | Independent-batch variance formula verified; an intentionally dependent-batch test fails that formula. | Invalid uncertainty calculation. |
| V05 | beta0, zero proxy variance, zero reference gap and all-equal values behave correctly. | Degenerate-case failure. |
| V06 | Explicit-world NOLO values reproduce traced old search on exactly those worlds; evaluator does not resample. | Wrong expensive target. |
| V07 | Action reorder changes only the corresponding deterministic NOLO columns; world inputs unchanged. | Buffer/order or hidden-state bug. |
| V08 | FIT/PLAN/SCREEN/CONFIRM parent-deal overlap is rejected; reference worlds independent of selection. | Data leakage/optimistic validation. |
| V09 | Shadow advancement matches original W128 RNG/config on the same history; natural-stream variant separately named. | Misattributed finite-seed policy change. |
| V10 | Timing includes sampling, shadow work, batching and proxy overhead; total-saving accounting respects branch fraction. | Spurious speed claim. |
| V11 | Reference-error contribution retained; MSE-ratio claim is not inferred from additive-noise cancellation. | Invalid 20% endpoint. |

## C2 consequential bids

| ID | Required test | Failure meaning |
|---|---|---|
| B01 | Forehand weighting unchanged, all-pass E=1 and never-pass E=0 with finite zero output. | Wrong event definition. |
| B02 | Same joint predecessor bids and E reused for every focal action; changing focal a cannot change E. | Counterfactual contamination. |
| B03 | Out-of-event rows contribute zero contrast while staying in denominator; zero-hit batches not resampled. | Selection bias. |
| B04 | Prefix shown cards originate in the predecessor's hand and satisfy mandatory declaration tiers. | Illegal reconstructed world. |
| B05 | A joint-hand toy differs from product-marginal approximation; evaluator retains joint constraints. | Invalid belief factorisation. |
| B06 | F/R/RC ablations separate reach and public-card selection; validation target is common across them. | Uninterpretable improvement. |
| B07 | Diagnostic all-four queries do not mutate live predecessor state; actual reached-call schedule recorded. | Cancellation assumptions fail. |
| B08 | Conditional and unconditional units are distinct; reach frequency and denominators stored. | Inflated gain. |

## C3 utility and kernel

| ID | Required test | Failure meaning |
|---|---|---|
| K01 | Utility certificate checks a safe superset of final trick totals for both contracts/declarer teams. | Unsound stopping. |
| K02 | Exact target equals old float-rounded delta; certified rows do not fabricate winner/tricks or double-record utility. | Wrong value/record. |
| K03 | Score48 with uncertain winner does not stop merely because score48; existing sooli shortcuts not relabelled. | Invalid/newly misclaimed optimisation. |
| K04 | Early-stopping batching effects checked on other rows; numerical parity claims limited to tested/proven scope. | Row-level proof overstated. |
| K05 | Cold/offer/play mode transitions compared against every relevant default setter and override. | 8100-state model not justified. |
| K06 | Known tiny kernels match an independent direct solve/simulation; reset and absorption implemented. | Kernel solver invalid. |
| K07 | Unobserved/nonabsorbing rows report unresolved, not smoothed or clipped values. | Fabricated identifiable estimate. |
| K08 | Whole-deck bootstrap retains all related row/arm samples; residual and numerical/estimated-kernel uncertainty separate. | False precision. |
| K09 | Marginal-RNG mode model named separately from literal B0; direct-match agreement is independently tested. | Unjustified baseline equivalence. |

## C4 joint exchange

| ID | Required test | Failure meaning |
|---|---|---|
| X01 | Giver/receiver52-card masks, ace-low features, receiver original-P reconstruction and no 156-head indexing. | Illegal/wrong model input. |
| X02 | Fixed legal input under changed other hidden hands gives identical features/policy distribution. | Hidden-hand sharing. |
| X03 |169 legal table branches validated on a bounded fixture; full continuation cost recorded. | Expensive proxy mistaken for scalar lookup. |
| X04 | Receiver objective weights messages by giver policy; exact two-world toy detects the unweighted error. | No valid convention learning. |
| X05 | Sampled-message proposal has support and explicit E/mu weighting, or full enumeration used. | Off-policy selection bias. |
| X06 | Soft training versus greedy deployment distinguished; greedy receiver distribution independently checked. | Wrong deployed-policy result. |
| X07 | Four-arm continuation snapshots/costs matched; shadow-state and natural-state variants separate. | State-advancement confounding. |
| X08 | Harmful/infrequent messages can lose; no test assumes signalling must help. | Vacuous optimisation test. |
| X09 | Historical shown card transfer and defender ignorance correct; dead partner never plays. | Exchange leakage/rules error. |
| X10 | Accepted/rejected source denominators and whole-deal splits retained; old v2 bank never used as fresh v3 confirmation. | Population/leakage error. |
| X11 | Joint-versus-each-single comparisons receive simultaneous analysis; no uncorrected chosen-best comparator. | Selection-biased claim. |
| X12 | Convention-aware defender weights independently justified or test labelled unresolved. | False posterior/robustness claim. |

## C5 information-consistent option

| ID | Required test | Failure meaning |
|---|---|---|
| O01 | Count before complete enumeration; partial support never labelled exact; strict/native-law mismatch rejected initially. | Model/support confounding. |
| O02 | v3 ruleset/public history/declined offers preserved in reconstruction; fixed clone gets its own masked view. | Wrong game or leakage. |
| O03 | Indistinguishable worlds with opposite optimal b require one shared action; distinguishable companion permits different b. | Strategy fusion remains. |
| O04 | Nonuniform posterior mass changes group expectation correctly; root key collisions intentionally rejected. | Bad grouping/probabilities. |
| O05 | Complete optimal option>=feasible root policy in identical fixed model; root-only clairvoyance>=option. | Optimiser/comparator bug. |
| O06 | Negative action-minus-reference gap exists; do not require negative optimum-minus-baseline as a test. | Invalid mathematical expectation. |
| O07 | Root RNG/snapshot is identical across indistinguishable histories; W128 comparator continues at later root turns. | Cheating or incomplete comparator. |
| O08 | Option persists without posterior reset; unexpected key/node cap/deadline falls back and is recorded. | Deployed action differs from valued option. |
| O09 | Two-card suffix is forced after current action; no invented extra future decision. | Wrong horizon logic. |
| O10 | Initial one-option-per-team/deal gate, coverage, support size and deadline/fallback cost retained. | Additive-regret or latency overclaim. |

## Empirical gates (not contract-test substitutes)

A contract pass only establishes implementation readiness. Each statistical experiment needs its own manifest, numeric approved resource limits, frozen candidate and independent data. Prioritise C1 planning; do not launch all workstreams because their code compiles. Record rejected or budget-unresolved hypotheses explicitly. Promotion requires the corresponding full-game test and independent confirmation. Deployment is separately authorised.
