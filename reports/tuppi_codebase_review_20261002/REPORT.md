# Tuppi codebase and research review

**2 October 2026.** Prepared for the owner's independent review assignment. This is a review and documentation delivery. Production policies, native libraries, models, training jobs and returned research packages were not edited by this review.

## Assessment

Tuppi is a substantial research platform with a working product attached. Its most valuable architecture is the separation between authoritative Python rules, immutable player observations, a fast differential-tested native implementation, transparent heuristic agents, and independent research instruments. The current playing bot combines a learned policy with sampled-world search and exact late-game solving. Those components now serve different roles; treating the bot as a single network, or as the old clone-search configuration, obscures both its strength and its costs.

The most promising near-term project work is to make comparisons reproducible and current configurations explicit, then remove measured infrastructure costs. There is already considerable prepared code for this in `TuppiAI-prior`. Developing another evaluation framework before validating that branch would duplicate effort. Further bot research should measure improvement against a frozen strong bot as well as the new heuristic benchmark, and evaluate strength per unit of compute and decision latency. A small positive proxy result or better prediction loss is insufficient.

Four Python control-flow issues were reproduced with actual source function bodies and dependency stubs. They concern persistent sampler settings, incompatible settings in searched-opponent evaluations, censored-match scoring, and adaptive budget overshoot. There are also supported risks around persistent controller state, learner endpoints, adaptive objective changes and documentation drift. These findings are useful repair candidates; they do not make the platform broadly unsound or invalidate results where their triggers were absent.

The report supplements existing documentation where the missing piece is the relationship between programmes, current configuration, native ownership and efficiency priorities. Existing detailed rules and historical method documents remain the canonical sources for their original experiments.

## Read the delivery

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Engine, bot, native, learner, server and Swift paths; contracts and current decision flow |
| [METHODS_AND_EVIDENCE.md](METHODS_AND_EVIDENCE.md) | What the different approaches do, what has been reported, and what each result establishes |
| [EFFICIENCY.md](EFFICIENCY.md) | Existing optimizations and ranked proposals with measurable acceptance criteria |
| [FINDINGS.md](FINDINGS.md) | Reproduced issues, qualified risks and concrete proposed fixes |
| [VALIDATION.md](VALIDATION.md) | Checks actually performed, source changes during review, limitations and reproduction commands |
| [SOURCE_INDEX.md](SOURCE_INDEX.md) | Generated source/package navigation and Python definition locations |
| [SOURCE_SNAPSHOT.json](SOURCE_SNAPSHOT.json) | Earlier source hashes, AST definitions, repository identities and dirty status |
| [SOURCE_SNAPSHOT_END.json](SOURCE_SNAPSHOT_END.json) | End-of-review inventory; compare this with the earlier snapshot |
| [SOURCE_PROBES.json](SOURCE_PROBES.json) | Exact source hashes, triggers and observed results for four control-flow probes |
| [SOURCE_PROBES_CURRENT.json](SOURCE_PROBES_CURRENT.json) | Final repeat of the probes after a further factory change |

## Workspace roles

These are checkout roles, not interchangeable import roots.

| Checkout/programme | Role in the inspected workspace | Use |
|---|---|---|
| `TuppiProject-current` | Authoritative v3 rules, engine, live server; branch `rules/project-target-v3-locked-bids` | Current game semantics and product |
| `TuppiClient-current` | Swift macOS client; branch `feature/v3-locked-bids-sooli` | Current app source |
| `TuppiAI` | Main native bot, clone, self-play/VRPO, search, evaluation and research modules | Current bot source; research results log |
| `TuppiAI-prior` | Isolated policy-prior, monitoring, evaluation and queue infrastructure | Prepared changes awaiting runtime validation; evolves independently |
| `TuppiAI-sp` | Self-play development branch | Historical implementation/evidence; much has reached main |
| `TuppiAI-perf` | Search-efficiency branch | Historical E0–E9 implementation/evidence |
| `TuppiAI-vn` | Value-leaf experiments | VN1/VN2 code and negative evidence |
| `TuppiProject` | Separate older-rule research checkout with substantial dirty work | NOLO, exact/reference and other research; preserve concurrent work |
| `TuppiClient` | Separate client working copy | Other author's work; not the current product checkout |
| `tuppi_execution_v2` | Returned portable CVR/JRPL planning and mathematics | Immutable input; not a drop-in runtime |
| `tuppi_execution_v2_output` | Earlier partial integration | Commissioning artifacts and adapters |
| `tuppi_execution_12h` | Capped CVR/JRPL execution and repair history | Separate frozen baselines, grants, ledgers and result interpretation |
| `tuppi_execution_sampler_v1` | Corrected-sampler CVR trial | B0-S1 repair evidence and separate trial |
| `audit_deliverables` | Registered handoffs, implementation outputs and this review | Discoverability and provenance |

The earlier inventory recorded 1,906 scoped files, including source, tests and selected documentation. It parsed Python ASTs without imports and reported no syntax errors. This count includes duplicated worktrees; it is not a count of unique production files or files manually reviewed. In that inventory, main AI had 21,077 Python lines and 8,669 C lines including research/test/build copies; `TuppiProject-current` had 103,756 Python lines including tests/tools, and the current client had 15,892 Swift lines including tests. The generated index and validation record explain coverage. The workspace continued changing after that inventory.

## What the current bot actually does

The source configuration in [best.py](../../TuppiAI/tuppi_ai/best.py) uses a clone for opponent rollouts, VRPO1 for the searching team's rollouts, and VRPO3 as a policy anchor. The factory default is **128 worlds**. The live server explicitly requests **1,024 worlds**, a **six-trick exact tail**, and adaptive bidding above 128 worlds with batch 128, z 2.5 and delta 0.005. The policy anchor keeps its preferred action unless search improves its estimated equity by more than **0.003**. Showing-fallback constraints are enabled for the normal factory. The normal sooli configuration searches offers, gives and play, uses a heuristic return, and applies mode-17 inference with tilt 0.3.

The final factory also exposes `RAMI_MARGIN=0.0`, passed as a negative RAMI bonus for the normal controller. Its default adds no offset; nonzero allocation variants need separate evaluation. These are source-confirmed settings. A process inspection saw a running server and a separate 12-worker heuristic evaluation, but this review did not interrogate server internals, inspect private rooms, restart the server or attest the loaded library/model hashes. Source settings and loaded-process settings are separate evidence.

At a normal root, search samples hidden layouts consistent with the observer's public information, prices legal actions on common worlds, follows the rollout models through their own local observations, then solves the late suffix with full information inside each sampled world. This is determinized policy improvement. The exact suffix is exact for that hypothetical full-information position; it does not make the original imperfect-information decision exact.

The current 156-output learned networks cover ordinary card play and bidding. Sooli adds actions up to 209 in the engine and bridge, and is handled through separate search/heuristic controllers. SP1 and VRPO therefore learn a policy within a fixed larger v3 controller, rather than learning all sooli choices through a 210-action head.

## Research evidence and its limits

The older Python PIMC, root-information UCT, multi-observer ISMCTS and finite behavioral-belief programmes retain useful negative results and tiny exact oracles. Their budgets, representations, rules and continuation policies differ from modern native search. Their failures should guide diagnosis, not become a blanket conclusion that search or learned policies cannot work in Tuppi.

The modern results log reports successful native clone-search, SP1 and privileged-Q VRPO development. Selected examples are retained in the methods ledger with their evaluator and date. Results were not rerun in this review. Main's benchmark changed on **2 October** from `partner_aware_lead_v2` to **v3**. Historical entries retain the v2 comparator, and the live search still models opponents with the v2 clone. Neither a stronger benchmark nor an opponent-model change should be silently substituted into old comparisons.

C0–C5 contract completion is separate from strength evidence. The implementation report records 109 passing contract tests; subsequent bounded screens did not support promotion of C1, C2 or C5. C1's targeted branch occupied about 1.3% of measured CPU in that historical configuration, imposing a hard ceiling on its whole-bot saving. C2's reach-conditioning screen did not improve validated bids; C5 frequently left its modelled support against actual search opponents.

The original CVR trial stopped on a sampled-world legality defect. A separate B0-S1 trial repaired the ordinary sampler, passed the recorded correctness checks, and then failed its investment screen. JRPL's recorded renewal ended with `NO_SUPPORTED_LEARNING_GAIN_OVER_INITIAL_CONTROL`. These are distinct outcomes against distinct frozen comparators. They should remain separate from present live strength and from the newer self-play programme.

## Efficiency priorities

1. **Validate and reuse the prepared infrastructure.** `TuppiAI-prior` has policy-prior diagnostics, split actor/critic decoding, grouped device reads, configurable monitoring, explicit final snapshots, censored-match bounds, searched-opponent setting guards, and now frozen queues/paired-result checks. Its standard-library checks are informative; native/Torch execution, identity equivalence, throughput and playing strength still require validation. Integrate in small independent patches after those gates.
2. **Measure the current bot before choosing another hot loop.** The September profile ranked bid rollouts, sooli offers, exact tails and rollout forwards. E0–E5 are already implemented. VRPO rollout roles, the sampler fix and the anchor have changed the workload. Re-profile by decision kind and record CPU, wall, model-forward rows, worlds/actions and tail nodes at the current live setting.
3. **Reduce overhead that does not add playing information.** Reuse private native scratch buffers, lazily allocate unused Python fallback buffers, export/share immutable model weights where safe, and avoid repeated anchor forwards/model construction. These are measurable implementation candidates, not demonstrated speedups.
4. **Treat allocation as part of the policy.** Adaptive pruning, the anchor margin, RAMI offsets and a soft prior must agree on their objective. Eliminated or partially priced actions need sample counts. A faster allocation that selects a different move requires paired strength and latency evidence.
5. **Spend research compute on complete decisions.** Use reusable diagnostic banks for development, whole-parent splits, fresh full-trajectory screens and a frozen confirmation budget. Report completed useful units and total cost, including monitoring, failed jobs, compilation, replication and final evaluation.

The ranked efficiency document gives specific paths, expected mechanisms, falsifiers and gates. It does not promise gains from old profile shares or recommend restarting expensive failed programmes automatically.

## Repairs worth prioritizing

Before new comparisons with two searched sides, port or validate the process-global setting guard and correct the unknown-outcome treatment for capped matches. Make factory configuration explicit and symmetric, while preserving frozen legacy baselines in isolated processes. Validate adaptive inputs and remaining batches. Correcting the known v3 sooli-setting persistence changes the comparator and needs a separately frozen baseline.

Modernize the *current* README/task status through small append-only status summaries, preserving dated historical reports. The AI README still describes clone-only rollouts and old timings; the efficiency plan still says installed speedups and B0-S1 are unmerged; the current engine README mixes v1-era restrictions with working v3 analysis. This review provides a dated cross-project description without rewriting those historical records.

The immediate sequence is: freeze one exact source/model/library/configuration bundle; run prepared correctness checks in its isolated checkout; validate zero-change parity and controller lifecycle; then measure one efficiency change at a time. Bot-strength variants follow with predeclared matched-compute comparisons. All experimental and deployment work remains outside this review's execution scope.
