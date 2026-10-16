# Methods and evidence ledger

Numbers below are **reported local evidence**, not experiments rerun in this review. Each row identifies the instrument and limits. Contemporary source changes are documented separately from historical results.

## Approaches

| Approach | Implemented mechanism and source | Evidence and current interpretation |
|---|---|---|
| Transparent heuristic ladder | `TuppiProject-current/src/tuppi_agents`: contract hand scores, public counting, partner-aware play and improved-rule registries | Observation-only explainable baseline; the benchmark changed to `partner_aware_lead_v3` on 2 October |
| Python PIMC | `tuppi_search/pimc.py`, hard-feasible worlds and heuristic/exact-tail continuations | Historical v1 programme negative at its tested budgets; strategy fusion and continuation mismatch explicitly investigated |
| Root-information UCT | `tuppi_search/root_info_uct.py`, root information-state nodes | Structural information-set control; historical weak reference result, not current native bot |
| Multi-observer ISMCTS | `tuppi_search/multi_observer.py`, actor-local redeterminization and availability-aware UCT | Tiny information-game oracle and privacy checks useful; optimized full-game programme still weaker than its reference |
| Exact hard inference | `tuppi_exact`, native sampler/DP | Legal support and uniform prior, not a behavioral opponent model |
| Behavioral belief | `tuppi_belief`, optional AI likelihood/belief networks | Tiny exact signal existed; finite candidate weighting suffered concentration; later live learned odds were not adopted |
| Exact NOLO security/support | Dirty `TuppiProject/src/tuppi_nolo`, independent certificate checks and compact backend | Research-private finite-support security claims; offline oracle usefulness does not imply real-time general coverage |
| Historical GRU/DeepSets imitation | `tuppi_learning`, old Phase 6 | Bounded imitation failed; a different corpus/architecture from the later successful native MLP clone |
| Native behavior clone | `TuppiAI/model.py`, clone assets, native MLP | Fast continuation policy for the older heuristic; clone fidelity and actual game strength are different metrics |
| Deep Monte Carlo from scratch | `TuppiAI/train.py`, chosen-action terminal equity targets | Reported poor action learning under large hidden-world target variance |
| Branch-label policy iteration | `TuppiAI/selfplay.py`, SP1/SP2/SP2b/SP3 | Common full-state action labels, centered advantages, conservative improvement and distillation; strong SP1 result, later variants plateaued/regressed under their gates |
| Privileged-Q VRPO | `TuppiAI/vrpo.py`, stochastic native trajectories, critic with hidden hands, PPO Q-boosted advantages | Current learned actors; per-deal surrogate objective and fixed sooli controller, not full-match RL |
| Policy-anchored native search | `TuppiAI/best.py`, `search.py`, `native/tuppi_env.c` | Current practical bot: small rollout models, larger root anchor, adaptive bids, exact suffix |
| Value leaves VN1/VN2 | `TuppiAI-vn`, `value.py`, value-leaf options | Tested and not adopted; better held-out prediction did not reliably improve decision quality/saving |
| C1 control variate | `tuppi_ai/research/c1_control_variate.py`, `c1_dispatch.py` | Contract implementation; low targeted CPU share limited whole-bot utility |
| C2 blind-bid reach conditioning | `research/c2_blind_bids.py`, stage screens | Contract implementation and bounded negative screens; smaller ESS and noisy bids mattered |
| C3b utility certificate / C3a reduced kernel | `research/c3_utility_stop.py`, `c3_kernel.py` | Correctness infrastructure; no present universal speed/strength claim |
| C4 joint exchange | `research/c4_exchange.py`, `c4_training.py` | Legal stage scoring and weighted joint objective contract; no adopted strength result |
| C5 contingent options | `research/c5_option.py` | Screen frequently left modelled support versus actual search; not promoted |
| CVR | Capped trial `code/cvr.py`, first-DD capture, outcome model and corrected continuation | Original baseline sampler defect blocked valid replay; separate B0-S1 trial failed investment screen |
| JRPL | Capped trial `code/jrpl.py`, modes, joint likelihood gradient, prefix reuse until divergence | Renewal reached recorded no-supported-learning-gain gate; not a broad impossibility result |
| Soft policy prior / integrated keep | `TuppiAI-prior/policy_prior.py`, `search.py` | Prepared allocation variants and diagnostic replay; runtime and strength unverified here |
| Headless LLM agent | Dirty `TuppiProject/src/tuppi_llm` | Observation-only tool/prompt/runtime adapter, separate budgets and fallback; not invoked or strength-qualified here |

## Selected locatable results

| Recorded result | Source and evidence class | Limits |
|---|---|---|
| Multi-observer standard: 1/6/25 W/T/L, pair p(win)=0.125 over 32 pairs | [Phase 5F results](../../TuppiProject-current/docs/search/phase5f_results.md), v1 complete-match development evaluation | Frozen old reference, small development bank, no promotion |
| Phase 6 imitation: 85.27% held-out agreement; 0/1/31 pair W/T/L | [Phase 6 results](../../TuppiProject-current/docs/learning/phase6_results.md), imitation plus complete matches | One corrected corpus/seed; no RL milestone; does not describe current MLP |
| Finite behavioral belief: hard-uniform NLL 1.050 vs matched 1.747; ESS 6.47/32 | [Phase 5G-B results](../../TuppiProject-current/docs/belief/phase5g_b_results.md), synthetic ownership diagnostic | Tiny exact oracle helped; finite practical representation failed; no human accuracy claim |
| SP1: 43 iterations, 86.6M labelled states; +0.0131 [+0.0119,+0.0143] without search | [selfplay.py](../../TuppiAI/tuppi_ai/selfplay.py) header and [results log](../../TuppiAI/docs/STATUS.md), reported authoritative duplicate-deal result | Labelled states are not 86.6M independent deals or learner updates; historical v2 heuristic opponent |
| VRPO2 vs VRPO1: +0.00066 [-0.00018,+0.00150] | [results log](../../TuppiAI/docs/STATUS.md), 1,024 fresh authoritative duplicate deals | Non-inferior by recorded rule; did not pass improvement bar |
| VRPO3 vs VRPO2: +0.00118 [+0.00022,+0.00215] | [results log](../../TuppiAI/docs/STATUS.md), 1,024 authoritative duplicate deals, no search | Historical comparator and predeclared rule; no complete-match rerun here |
| Anchor vs plain search at W1024: +0.00267 [+0.00160,+0.00374], CPU +3% | [results log](../../TuppiAI/docs/STATUS.md), 512 duplicate deals | Specific keep/rollout setting; does not justify transferring all W128 margin choices |
| VRPO3 vs VRPO1 anchor at W1024: +0.00005 [-0.00083,+0.00092], CPU -2% | [results log](../../TuppiAI/docs/STATUS.md), paired duplicate-deal comparison | Neutral at live strength; larger actor's no-search gain did not transfer at this setting |
| E0–E5: 2.17× W1024 wall speed; E7 about 1.5× lower CPU/deal | [efficiency plan](../../TuppiAI/docs/EFFICIENCY_PLAN.md) and results log, profiling/paired measurements | Different changes and metrics; not multiplicative without a common baseline |
| C1 NOLO-discard cost fraction about 1.3% | [implementation report](../tuppi_implementation_output/IMPLEMENTATION_REPORT.md), bounded 12-deal cost screen | Old configuration; cost ceiling argument, not current profiler share |
| C5: 11 of 14 started options left support at next decision | Same implementation report, bounded stage-1 screen | Support/model mismatch versus actual W128 opponents; no promotion |
| C2 equal-effective-sample conditioned pick -0.0005 ±0.0003 per reached call | Same implementation report, stage-2 diagnostic | No full-game strength claim; fresh resamples alone often changed near-tied bids |
| Corrected CVR: screen mean -0.0001983, planning interval [-0.0068973,+0.0065007], CPU ratio 1.037 | [CVR results](../../tuppi_execution_sampler_v1/CVR/RESULTS.json), 1,024-parent independent screen | B0-S1 comparator; z=2.4 planning interval, not confirmation inference; failed investment gate |
| JRPL renewal: mean 0.0, 128 controls; no supported learning gain | [JRPL result](../../tuppi_execution_12h/JRPL/RESULTS.json), initial-policy control gate | No major gain confirmed; scientific gate and partial/underexposed paths remain distinct |

## Evaluation designs must be named

Main duplicate evaluation uses **four hand rotations × two team assignments** per base deal, dealer 0, with uncertainty over base-deal aggregates. `scores=zero` and `scores=uniform` differ. Legacy uniform chooses a level 0–12 uniformly then a side: P(0–0)=1/13 and each other reachable state 1/26. It is not uniform over the 25 reachable nonterminal states. `research/runner_v3.py` names that design `legacy_uniform` and separately supports `uniform25`.

Native training checks compare policies in the fast engine and are useful monitoring screens. They do not attest the authoritative-engine policy wrapper, live controller lifecycle, full match outcome or human partnership. Complete-match complementary legs share an indexed stream and run to natural termination; capped legs are unresolved. Human-versus-bot same-card comparisons are another endpoint and should retain human seat/partner context.

Offline mining measures one-step substitutions under a fixed continuation. A sum of those prices is not the outcome of changing every decision. Choosing the best shown card using true-world outcomes can flatter the contract with more variable outcomes; H2's recorded calibration failure illustrates that. Behavioral inference also depends on which opponent population generated the history.

## Current status is separate from returned plans

The C0–C5 handoff's task DAG and acceptance tests are immutable planning inputs; progress lives in the implementation output and pilot reports. The self-play packet proposes repaired SP1, privileged-Q VRPO, PPO-V controls and complete-match objectives; main now contains later actual SP/VRPO work, but not every proposed arm/objective. Registering a packet does not establish those comparisons or authorize reopening experiments.

On 2 October, isolated infrastructure expanded during this review from commit `319e121` into queue/provenance work. Main also changed RAMI-bonus/adaptive logic. The earlier and ending snapshots preserve that distinction. No newly observed commit is labelled a speed or strength gain without its own evidence.
