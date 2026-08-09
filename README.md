# Tuppi research project

This repository contains the frozen Phase 0B legacy harness, the Phase 1
authoritative rules specification, the Phase 2 deterministic clean engine,
the Phase 3 deterministic evaluation framework, the Phase 4 transparent
baseline-agent ladder, the Phase 5A complete-match evaluation protocol, the
Phase 5B exact inference and solving layer, the Phase 5C uniform-feasible PIMC
search baseline, and the Phase 5D-A decomposition of that baseline's failure.
Phase 5D-B and Phase 5E added observation-safe root information-set UCT and
multi-observer re-determinizing search; Phase 5F accelerates the latter without
changing its semantics and records its first valid unsealed strength evaluation.

Nine boundaries matter:

1. `Archive/` contains byte-for-byte frozen historical artifacts.
2. `src/tuppi_legacy/` verifies and executes the old emulator through an
   external, finite, all-AI adapter.
3. `project_target_v1` is the authoritative future ruleset. Its pure executable
   reference is in `src/tuppi_rules/`; it is not a complete game engine.
4. `src/tuppi_engine/` is the clean deterministic state machine around those
   rules. It has no dependency on the legacy adapter.
5. `src/tuppi_eval/` owns deal banks, agent/team identities, balanced schedules,
   finite arena execution, paired statistics, and baseline cross-play.
6. `src/tuppi_agents/` owns the deterministic observation-only baseline agents.
   It consumes player-specific observations and never private engine state, and
   it contains no search, learning, or belief model.
7. `src/tuppi_match/` owns the complete-match duplicate protocol: extensible
   deterministic streams, complementary leg pairs run to natural termination,
   match win probability as the primary endpoint, and separated development,
   calibration, and sealed fixture banks.
8. `src/tuppi_exact/` owns the exact layer: the hard public constraint model, the
   exact feasible-assignment counter, the exactly uniform hidden-hand sampler,
   engine-validated hypothetical continuations, and the exact late-game solver.
   Everything in it is exact or an error, and the dependency direction is
   one-way: it reads the earlier packages and none of them may reference it.
9. `src/tuppi_search/` owns the search baselines: uniform-feasible PIMC,
   root-player information-set UCT, and observation-safe multi-observer
   re-determinizing search. They are baselines, not equilibrium solvers, and the
   dependency direction is one-way again: nothing earlier may reference it.

The archival ruleset identifier is **`legacy_v9_unverified`**. It is not the
target ruleset, is preserved only for historical comparison, and must not be
described as following official tournament rules.

## Authoritative target rules

The project owner's Finnish specification dated 2026-07-31 is formalized as
**`project_target_v1`**. It is authoritative for this project but does not claim
general official status.

- Principal engineering specification: `docs/rules/project_target_v1.md`
- Finnish specification: `docs/rules/project_target_v1.fi.md`
- Traceable decision table: `docs/rules/project_target_v1_decisions.md`
- Machine-readable configuration: `configs/rules/project_target_v1.json`
- Strict schema: `schemas/ruleset.schema.json`
- Pure executable reference: `src/tuppi_rules/`
- Executable examples: `examples/rules/project_target_v1/`

The reference package defines immutable cards, showing, contract resolution,
legal trick play, complete-deal validation, deal scoring, and rising-score
transitions. It contains no randomness, I/O, game loop, agents, search, or
legacy imports.

## Clean deterministic engine

`src/tuppi_engine/` owns complete private hands and executes full explicit
deals and matches under `project_target_v1`. Its public action boundary is
strict: invalid actors, cards, phases, shows, and follow-suit violations raise
typed errors and are never replaced with a fallback action.

Agents receive only frozen `PlayerObservation` values containing their own
hand and public history. Opponent hands, content-derived deal identifiers, RNG
state, and private engine objects are absent. This is a formally audited API
boundary, not an operating-system sandbox for arbitrary hostile Python code.

Engine documentation:

- Architecture: `docs/engine/architecture.md`
- State machine: `docs/engine/state_machine.md`
- Observation security: `docs/engine/observation_security.md`
- Serialization and visibility: `docs/engine/serialization.md`
- Strict schemas: `schemas/engine/`
- Explicit examples and scripts: `examples/engine/project_target_v1/`

The engine contains no random dealing. A runner must supply complete ordered
hands, an explicit dealer, and a valid starting score. Canonical public event
logs contain only accepted public actions. Separate research-private results
are explicitly labeled and retain full initial hands for reproducibility.

## Supported Python

The package declares Python 3.11 through 3.14 (`>=3.11,<3.15`). The original
audit and frozen manifest were produced with Python 3.14.3.

## Installation

Create an isolated environment and install the packages plus development
dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
```

If the working tree is on a cloud-synced filesystem, put the environment
**outside** it instead. A synced `.venv` was the reproducible cause of a stalled
CLI subprocess test:

```bash
python3 -m venv "$HOME/.venvs/tuppi-research"
source "$HOME/.venvs/tuppi-research/bin/activate"
python -m pip install -e '.[dev]'
```

There are no runtime dependencies outside the Python standard library and no
machine-learning dependencies. Development tests use pytest, Hypothesis, and
JSON Schema validation.

## Tests

```bash
.venv/bin/python -m pytest
```

`tests/legacy_characterization/` records observed legacy behavior, including
known defects. `tests/archival_harness/` tests the external adapter. Neither is
a normative test suite for the future engine.

Run only the authoritative rules tests with:

```bash
.venv/bin/python -m pytest tests/rules/project_target_v1
```

These tests derive solely from the project-owner specification and include
exhaustive scoring cases plus deterministic property-based checks.

Run only the clean-engine tests with:

```bash
.venv/bin/python -m pytest tests/engine
```

The engine suite includes adversarial hidden-hand isolation, complete scripted
deals and matches, strict schema validation, canonical determinism, and
property-based state invariants.

## Clean engine execution

Run one complete explicit all-NOLO deal:

```bash
.venv/bin/python -m tuppi_engine.runner \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --agents scripted,scripted,scripted,scripted \
  --script-file examples/engine/project_target_v1/full_nolo_script.json \
  --output engine-result.json \
  --event-log public-events.json
```

Run the four-deal scripted match that finishes exactly at 52:

```bash
.venv/bin/python -m tuppi_engine.runner \
  --deal-file examples/engine/project_target_v1/exact_52_match.json \
  --agents scripted,scripted,scripted,scripted \
  --script-file examples/engine/project_target_v1/exact_52_script.json \
  --output exact-52-result.json \
  --event-log exact-52-public-events.json \
  --require-complete-match
```

The runner is finite and uses no stdin, GUI, network, or hidden randomness.
Unknown fields, noncanonical cards, identifier mismatches, script exhaustion,
out-of-order scripts, illegal actions, shared cross-seat agent objects, extra
post-terminal deals, non-regular inputs, and invalid or aliased paths fail
nonzero.
Output path and stderr verbosity are excluded from canonical result content.

## Deterministic evaluation

`src/tuppi_eval/` compares immutable agent partnerships using content-addressed
deal banks and the documented eight-game `balanced_duplicate_8_v1` schedule.
The independently generated base deal—not each correlated seat rotation—is the
primary statistical unit. Failed rows are quarantined and excluded from normal
outcome metrics; completed atomic shards resume without replay.

Generate a deterministic one-deal bank:

```bash
.venv/bin/python -m tuppi_eval.runner generate-deals \
  --count 1 --seed 1729 --dealer-policy round_robin \
  --initial-dealer 0 --starting-score 0-0 \
  --output deal-bank.json
```

Run or resume the checked-in baseline fixture and rebuild its summary:

```bash
.venv/bin/python -m tuppi_eval.runner compare \
  --config examples/evaluation/baseline_comparison.json \
  --deal-bank examples/evaluation/small_deal_bank.json \
  --output-dir runs/baseline

.venv/bin/python -m tuppi_eval.runner summarize \
  --run-dir runs/baseline
```

Run deterministic baseline cross-play:

```bash
.venv/bin/python -m tuppi_eval.runner crossplay \
  --config examples/evaluation/baseline_crossplay.json \
  --deal-bank examples/evaluation/small_deal_bank.json \
  --output-dir runs/baseline-crossplay
```

These simple policies are evaluator fixtures, not strategic-strength claims.
The evaluator adds no search, learning, belief model, expert policy, GUI, or
network play. See `docs/evaluation/` for architecture, the exact schedule proof,
statistics, reproducibility, and registry semantics. Strict schemas are in
`schemas/evaluation/`, and CI-sized fixtures are in `examples/evaluation/`.

Run only Phase 3 tests with:

```bash
.venv/bin/python -m pytest tests/evaluation
```

## Transparent baseline agents

`src/tuppi_agents/` is a ladder of deterministic, observation-only agents. It is
a **reproducible reference population, not a strong player**. No agent here is
expert-validated, tuned, or claimed to be good.

| Rung | Agent | Capability added |
| --- | --- | --- |
| 1 | `legacy_heuristic_port_v1` | The frozen legacy public-information heuristic, ported to `project_target_v1` with no legacy import and no rollouts. |
| 2 | `reactive_contract_v1` | Own hand, current trick, seat relations, contract, legal actions. |
| 3 | `public_counting_v1` | Hard public inference: proven voids, public card accounting, certain winners. |
| 4 | `partner_aware_v1` | Explicit partnership rules, including the mechanical NOLO team-count consequence. |
| 5 | `match_aware_v1` | Deterministic rising-score rules for showing and play. |

Three further profiles exist only as ablation variants:
`reactive_contract_legacy_show_v1`, `partner_aware_legacy_convention_v1`, and
`match_aware_no_match_features_v1`. The Phase 3 fixtures (first legal, lowest
legal, highest legal, seeded random, fixed scripted) are re-exported as protocol
controls, not reimplemented, and are not rungs of the ladder.

Every policy receives only a frozen `PlayerObservation`, scores every legal
action into a named lexicographic vector, and breaks ties by the lowest engine
legal-action index. There is no PIMC, Monte Carlo search, determinization,
hidden-hand sampling, belief model, solver, learning, or self-play anywhere in
the package, and the test suite enforces that by parsing the source.

List the registered agents, profiles, and partnerships:

```bash
.venv/bin/python -m tuppi_agents.runner agents
```

Play one fixed deal and capture privacy-safe decision diagnostics:

```bash
.venv/bin/python -m tuppi_agents.runner play-deal \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile match_aware_v1 \
  --output ladder-result.json \
  --diagnostics ladder-diagnostics.json
```

Write the strategy-rule and profile catalogues, or explain a single decision:

```bash
.venv/bin/python -m tuppi_agents.runner catalogue --output rules.json
.venv/bin/python -m tuppi_agents.runner profiles --output profiles.json
.venv/bin/python -m tuppi_agents.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile partner_aware_v1 --output first-decision.json
```

Reproduce the frozen Phase 4 baseline evaluation (tens of minutes, resumable):

```bash
.venv/bin/python -m tuppi_agents.runner run-suite \
  --bank-dir banks --output-dir runs/phase4 \
  --report reports/phase4/baseline_report.json --only all
```

Agent documentation:

- Architecture and the observation-only boundary: `docs/agents/architecture.md`
- Hard inference versus probabilistic belief: `docs/agents/public_inference.md`
- Profiles, thresholds, and limitations: `docs/agents/baseline_profiles.md`
- The legacy port and its deviations: `docs/agents/legacy_port.md`
- Every strategy rule and its provenance: `docs/agents/strategy_rule_catalogue.md`
- Evaluation protocol and results: `docs/agents/phase4_evaluation.md`
- Strict schemas: `schemas/agents/`; CI-sized examples: `examples/agents/`
- Committed deal banks: `banks/`; manifests: `manifests/phase4/`; report:
  `reports/phase4/`

The committed banks are **development banks**: they were visible while the
agents were written, so their results are descriptive and are not sealed
promotion evidence.

Run only Phase 4 tests with:

```bash
.venv/bin/python -m pytest tests/agents
```

## Complete-match evaluation

`src/tuppi_match/` measures agents on **matches**, not deals. Phase 4 showed why
that is necessary: a partnership that is behind scores nothing for any win, so
signed deal points are blind to match safety, and Phase 4's 40-deal cap sat near
the median match length and censored roughly a third of all pairs.

The protocol runs, for each independent stream, two complementary legs from 0-0
on the *same* extensible deterministic deal stream: the candidate takes seats 0
and 2 in Leg E and seats 1 and 3 in Leg O. Each leg runs until a partnership
reaches 52; the legs may take different numbers of deals and the longer one is
never truncated. The pair value is

```text
D_match = (Y_E - Y_O) / 2        # +1 candidate wins both, 0 split, -1 opponent wins both
```

and the primary endpoint is the candidate's match win probability
`(1 + mean(D_match)) / 2`. The complete pair is the only independent unit; legs,
deals, tricks, and decisions are never counted as observations. A leg that hits
the infrastructure safety cap is `censored_infrastructure` - never a draw, never
a policy result - and its pair is excluded from the primary analysis entirely.

Verify that the Phase 4 agents have not moved, then run a calibration:

```bash
.venv/bin/python -m tuppi_match.runner freeze \
  --verify reports/phase5a/phase4_frozen_agents.json

.venv/bin/python -m tuppi_match.runner run \
  --design calibration --pairs 256 --safety-cap 704 \
  --output-dir "$TMPDIR/tuppi-phase5a/calibration" --workers 6
```

Write experiment output to **local scratch, never inside this iCloud-synced
tree**; see `docs/match/complete_match_protocol.md`.

Match documentation:

- Protocol, streams, storage, and CLI: `docs/match/complete_match_protocol.md`
- Deal-level versus match-level endpoints: `docs/match/endpoints.md`
- Censoring policy and safety-cap calibration: `docs/match/censoring.md`
- Bank roles and sealed-bank handling: `docs/match/bank_lifecycle.md`
- Calibration methodology and sample sizes: `docs/match/calibration.md`
- Results and ladder reassessment: `docs/match/phase5a_results.md`

Run only Phase 5A tests with:

```bash
.venv/bin/python -m pytest tests/match
```

## Exact inference, exact solving, and rule diagnosis

`src/tuppi_exact/` is the Phase 5B layer that sits on top of Phase 4's hard public
inference. Five capabilities, all exact:

| Module | Question it answers exactly |
| --- | --- |
| `constraints` | Which seats may still hold this card? |
| `counting` | How many hidden-hand assignments does public information permit? |
| `sampling` | Draw one of those, exactly uniformly. |
| `continuation` | Turn a sampled assignment into a playable engine state. |
| `solver` | What is optimal play here under perfect information? |

Nothing here estimates. A position beyond the exact budget raises
`SolverBudgetError` instead of answering approximately, and
uniform-over-feasible is recorded as a neutral reference measure, **not** a
posterior over opponent hands.

Phase 5B adds one exclusion Phase 4 did not model: a public show action proves
what the shower's whole hand does *not* contain, because `verbal_required` is
derived from the complete 13-card hand. Without it the sampler proposes
assignments the engine rejects.

Verify the frozen baseline, then diagnose the rising-score rules:

```bash
.venv/bin/python -m tuppi_exact.runner integrity \
  --verify reports/phase5b/frozen_baseline.json

.venv/bin/python -m tuppi_exact.runner monotonicity
.venv/bin/python -m tuppi_exact.runner variants

.venv/bin/python -m tuppi_exact.runner diagnose \
  --census-deals 24 --samples-per-decision 16 --show-census-deals 384 \
  --output "$TMPDIR/tuppi-phase5b/diagnosis.json"
```

Inspect or solve one position:

```bash
.venv/bin/python -m tuppi_exact.runner inspect \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --seat 1 --tricks 9 --samples 8

.venv/bin/python -m tuppi_exact.runner solve \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --tricks 10
```

**The central Phase 5B result.** Match utility is weakly monotone in the trick
split for every contract, declarer, and score state, so every trick-optimal card
is also match-optimal under perfect information. A rule that changes a *card*
therefore cannot buy anything the score makes valuable. Measured against that:
`match.play.coast_when_margin_worthless.v1` is exactly match-neutral,
`match.play.secure_decisive_trick.v1` is redundant - its condition held 510 times
and it changed 0 of 11 232 decisions - and only the two showing rules can move a
match. The protect threshold is not retunable, because the reachable score lattice
leaves it three distinct behaviours and the more it fires the worse it does. No
result establishes harm; every interval contains 0.5.

Exact-layer documentation:

- Architecture and the one-way boundary: `docs/exact/architecture.md`
- The constraint model and the show deduction: `docs/exact/constraint_model.md`
- Counting, uniform sampling, and the posterior caveat: `docs/exact/counting_and_sampling.md`
- Hypothetical continuations: `docs/exact/continuation.md`
- The solver and the monotonicity theorem: `docs/exact/solver.md`
- The frozen-baseline gate: `docs/exact/integrity.md`
- Results and the rule diagnosis: `docs/exact/phase5b_results.md`
- Strict schemas: `schemas/exact/`; reports: `reports/phase5b/`

Run only Phase 5B tests with:

```bash
.venv/bin/python -m pytest tests/exact
```

## Search: uniform-feasible PIMC

`src/tuppi_search/` is the Phase 5C baseline. For one decision it builds the Phase 5B
hard constraint set, samples an indexed set of uniformly feasible worlds, forces
**every** legal root action into **every** world of that one common set, completes each
deal with observation-only rollout policies, averages root-team utility, and selects
deterministically.

It is a **PIMC baseline, not an equilibrium solver**, and must never be described as
optimal imperfect-information play. Each sampled world is evaluated as a complete world
and the averaging happens afterwards, so PIMC can combine mutually incompatible
world-specific plans - *strategy fusion* - and more samples shrink Monte Carlo error
without touching that bias.

Phase 5C adds no information-set tree search, no persistent tree, no neural model, no
learned belief weighting, no particle filter, no CFR, and no training of any kind.
`tuppi_search.validation` scans for those families.

```bash
.venv/bin/python -m tuppi_search.runner validate
.venv/bin/python -m tuppi_search.runner agents
.venv/bin/python -m tuppi_search.runner utilities

.venv/bin/python -m tuppi_search.runner explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile uniform_feasible_pimc_smoke_v1 --seat 1 --tricks 9
```

**The central Phase 5C result is negative, and it is preserved as measured.** Over 32
complementary complete-match pairs from 0-0, `uniform_feasible_pimc_small_v1` lost to
`development_reference_v1` (`partner_aware_v1`) with `p_win = 0.156`, CI
[0.075, 0.238], sign-flip p = 0.0001, and **0 wins / 10 ties / 22 losses**. Zero legs
were censored and zero decisions failed, so this is a strength result rather than a
harness defect.

A dedicated showing census refuted the obvious explanation: PIMC's RAMI declaration
rate *rises* with the world budget (0.458 at 2 worlds to 0.583 at 16, against the
reference's 0.417), so small-sample selection optimism is not the mechanism. What
survives is policy mismatch - PIMC values an action assuming *reference* play by its own
partner, while both its seats actually play PIMC - and root strategy fusion. See
`docs/search/phase5c_evaluation.md`.

Search documentation:

- Architecture and why ISMCTS is deferred: `docs/search/architecture.md`
- The algorithm and strategy fusion: `docs/search/uniform_feasible_pimc.md`
- The rollout boundary: `docs/search/rollout_security.md`
- The exact tail and its bias: `docs/search/exact_tail_integration.md`
- Utility adapters: `docs/search/utilities.md`
- Determinism and the seed hierarchy: `docs/search/determinism.md`
- Budgets, benchmarks, and results: `docs/search/phase5c_evaluation.md`
- Strict schemas: `schemas/search/`; examples: `examples/search/`; reports: `reports/phase5c/`

Run only Phase 5C tests with:

```bash
.venv/bin/python -m pytest tests/search
```

## Phase 5D-A: decomposing the PIMC failure

Phase 5D-A asks *which* decisions lost the Phase 5C matches, before committing to another
search family. It adds only controlled PIMC variants and diagnostics - no ISMCTS, no
persistent tree, no learned partner model, no particle filter, and **no recursive PIMC**,
which `tuppi_search.validation` scans for structurally: the modules a rollout executes may
not construct a search agent at all.

Two phase-gated variants partition full PIMC's decisions, each with its own immutable
identity, composed from an *unmodified* `PimcConfiguration` so every Phase 5C content
address stays exactly as committed:

- `uniform_feasible_pimc_play_only_v1` - the frozen reference chooses the contract, PIMC
  plays every card.
- `uniform_feasible_pimc_show_only_v1` - PIMC chooses the contract, the frozen reference
  plays every card.

```bash
.venv/bin/python -m tuppi_search.runner diagnostic-agents
.venv/bin/python -m tuppi_search.runner corpus --showing 128 --trick-play 256 --workers 8 --output /tmp/c.json
.venv/bin/python -m tuppi_search.runner converge --budgets 2,4,8,16,32 --workers 8 --output /tmp/v.json
.venv/bin/python -m tuppi_search.runner decompose --workers 8 --output /tmp/d.json
```

**Both phases lose separately, and neither alone explains the loss.** Play-only reaches
`p_win = 0.250` and show-only `0.333` over 12 complete-match pairs each on a fresh
development bank, against the Phase 5C full-PIMC baseline of 0.156. They lose differently:
play-only loses tricks (191 vs 205), while show-only wins tricks evenly (184 vs 182) and
still loses points by over-declaring RAMI (0.905 share of deals against play-only's 0.780).

The corrected convergence run covered 112 positions: adjacent agreement was 0.839, 0.830,
0.839, and 0.875 from 2 to 32 worlds, while tie-breaking remained common. The full
decomposition covered 768 positions. PIMC's rollout still models a partner that is not
there: with a reference partner the assumed continuation matched perfectly (32/32 control
positions), but with a PIMC partner it diverged in 29/32 within the first action or two.

The seat-balanced heterogeneous comparison was also negative in both arrangements (p_win
0.333 and 0.375), so Phase 5D-A selects **Path D**: freeze PIMC as a negative baseline and
proceed to observation-safe information-set search. This is development evidence, not
promotion evidence.

The Phase 5C negative result is preserved exactly as measured under the frozen designation
`uniform_feasible_pimc_small_v1_negative_baseline` - metadata only, with the agent id,
configuration id, and committed registry digest all unchanged.

One instrument defect is recorded rather than quietly fixed: the first decision corpus drew
all 96 of its trick-play positions from a *single* set of hands, which inflated an apparent
"perfectly one-directional" RAMI bias that the corrected 64-hand corpus shows is 3.7 : 1.
`build_corpus` now caps the positions any one hand may contribute, and
`tests/search/test_phase5d_diagnostics.py` asserts the deal-spread property.

- Hypotheses, instruments, and their limits, written before the measurements:
  `docs/search/phase5d_a_hypotheses.md`
- Results and the selected decision path: `docs/search/phase5d_a_results.md`
- Reports: `reports/phase5d_a/`; schemas: `schemas/search/phase5d_a_*.schema.json`

## Phase 5D-B: root-player information-set UCT

Phase 5D-B adds `root_info_uct_v1`, a deliberately narrow observation-safe tree
searcher. It samples exact hard-feasible worlds, but keys all future root-player
nodes only by the root observation, so equivalent hidden worlds share one
contingent root policy. Partner and opponents remain frozen observation-only
`partner_aware_v1` rollouts; showing remains exactly `partner_aware_v1`; exact-tail
solving is off; the tree is not persistent and no recursive search is used.

```bash
.venv/bin/python -m tuppi_search.runner b-agents
.venv/bin/python -m tuppi_search.runner b-explain \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --profile root_info_uct_smoke_v1 --seat 1 --tricks 9
```

The finite independent reference and its PIMC strategy-fusion counterexample are
in `docs/search/tiny_exact_information_reference.md`. The implementation and
node-key contract are in `docs/search/root_information_uct.md` and
`docs/search/information_state_nodes.md`; development results and the E2 decision
gate are recorded in `docs/search/phase5d_b_results.md`. All bulk runs stay under
the permitted local `/Users/pyryouri/Developer/TuppiRuns/phase5d-b` directory,
and the sealed bank remains closed. The current small-budget result is
structurally correct but compute-limited; it is not a promotion or strength claim.

## Phase 5D-C: semantics-preserving UCT optimization

Phase 5D-C keeps every Phase 5D-B search identity, budget, rollout, utility,
normalization, node key, and tie-break unchanged. It adds a search-local immutable
trick-play state and formal observation projection that omit engine event-log
construction and repeated full-state validation inside hypothetical simulations.
The authoritative engine remains the differential reference. The optimized path
is documented in `docs/search/phase5d_c_optimization.md`, with profiling and results
in the three Phase 5D-C documents. Bulk profiles, conformance records, and the
unsealed 32-pair strength evaluation stay under
`/Users/pyryouri/Developer/TuppiRuns/phase5d-c`.

## Phase 5E: multi-observer re-determinizing search

Phase 5E adds the narrow `redeterminizing_ismcts_v1` baseline. It keeps one
fresh tree per real decision, namespaces information nodes by physical seat,
and re-determinizes non-root tree decisions from the acting seat's formal
observation using the exact Phase 5B sampler. The parent root-consistent world
is never replaced by an observer-local world; only a legal selected card is
mapped back to the parent. Showing remains frozen `partner_aware_v1`, exact-tail
is disabled, and fallback rollouts remain observation-only `partner_aware_v1`.
The specification and privacy contract are in `docs/search/multi_observer_search.md`,
`docs/search/redeterminization.md`, and `docs/search/observer_privacy.md`.
Phase 5E development output stays under the permitted local
`/Users/pyryouri/Developer/TuppiRuns/phase5e` directory.

## Legacy headless execution

Generate and play one fully materialized deal, with separate seeds for deal
generation and the legacy shared search stream:

```bash
.venv/bin/python -m tuppi_legacy.run \
  --deals 1 \
  --deal-seed 1729 \
  --legacy-rng-seed 2718 \
  --rollouts 1 \
  --scoring rising \
  --output results.jsonl
```

Use `--show-ban none` for a genuinely empty banned-rank set. Invalid counts,
budgets, ranks, deal files, or incompatible combinations fail with a nonzero
exit status.

Run the checked-in fixed deal instead of generating one:

```bash
.venv/bin/python -m tuppi_legacy.run \
  --deals 1 \
  --deal-file examples/legacy_deal_seed_1729.json \
  --legacy-rng-seed 2718 \
  --rollouts 1 \
  --scoring rising \
  --output fixed-results.jsonl
```

Output is canonical compact JSONL: one result object per deal. Complete initial
hands are intentionally retained as offline research data. They are not added
to the observations passed to legacy player decisions.

Generated deals use the versioned
`sha256_counter_fisher_yates_v1` generator, which does not touch Python's
module-global RNG. All requested deals are materialized before legacy play.
Each deal ID is a SHA-256 digest over its canonical schema version, card
encoding, dealer, and four ordered hands; provenance and file paths do not
change deal identity.

The result's effective gameplay configuration records whether deals were
generated, loaded from an explicit file, or supplied programmatically. It also
records a canonical digest of the complete materialized deal set and, for
generated input, the generator, generation seed, and initial dealer. Output
paths and logging verbosity are intentionally excluded because they cannot
affect play.

An explicit file may contain one `tuppi.legacy.deal.v1` object or a
`tuppi.legacy.deal_set.v1` object with a non-empty `deals` array. The loader
recalculates every ID and rejects malformed encodings, hand sizes, card ranges,
duplicates, unknown fields, and file/count mismatches.

Schemas:

- `schemas/legacy_deal.schema.json`
- `schemas/legacy_deal_set.schema.json`
- `schemas/legacy_result.schema.json`

## Fidelity limitations

- Gameplay and PIMC still use the legacy implementation and its single shared
  rollout RNG stream. Only deal generation/injection is separated from it.
- The adapter records actions through subclasses that call the unchanged
  `MonteCarloAI` methods, and suppresses presentation output. It does not parse
  that output.
- The legacy constructor cannot preserve an empty banned-rank set. The adapter
  applies the exact validated set to the public game attribute immediately
  after construction and records this workaround as a fidelity warning.
- The adapter injects a materialized deck by temporarily rebinding the frozen
  module's `random` name; stdout suppression is process-wide. The archival
  runner is therefore intentionally single-threaded.
- The adapter does not fix legacy rules, invalid-action fallbacks inside PIMC,
  mutable observations, or imperfect-information sampling.
- The missing GUI host is not reconstructed and the GUI is never imported.
- Byte-identical play is guaranteed for the same explicit deal, gameplay
  configuration, legacy RNG seed, Python version, and frozen artifact. The
  exact Python version is recorded because cross-version legacy RNG identity is
  not assumed.

See `docs/phase0_audit.md` and `manifests/legacy_v9.json` for the preserved
audit and artifact hashes.

## Development sequence

`src/tuppi_rules/` remains the executable specification, `src/tuppi_engine/` is
the playable deterministic state machine, `src/tuppi_eval/` is the controlled
evaluation framework, and `src/tuppi_agents/` is the transparent reference
population that framework measures.

Phase 4 deliberately stops short of strength work. It provides readable
baselines, hard public inference separated from any belief model, stable rule
provenance, and a reproducible evaluation protocol. Phase 5A replaced the deal
endpoint with match win probability; Phase 5B added the exact layer a search agent
needs and used it to diagnose Phase 4's rising-score rules. No legacy result is a
strength benchmark unless independently reproduced, and no Phase 4, 5A, or 5B
result is an expert-strength claim.

Phase 5C built the PIMC baseline on those capabilities and measured it losing
decisively to the development reference, with a named mechanism. Phase 5D-A completed
the behavioral decomposition and selected Path D; Phase 5D-B/C validated and optimized
root information-set UCT; Phase 5E/F validated and optimized observation-safe
multi-observer re-determinizing search. Phase 5G-A audits cross-bank evaluation
consistency before any behavioral belief model is introduced. All search identities and
the negative PIMC baseline remain frozen, and the promotion-sealed bank stays closed.

## Storage discipline

Only compact schemas, fixtures, benchmark summaries, and documentation belong in
Git. High-volume run output belongs on a plain local filesystem outside the
repository, outside `~/Documents`, and outside any cloud-synced directory: a
cloud-synced working tree was the reproducible cause of a stalled CLI subprocess
test. `python -m tuppi_exact.runner integrity --report` warns when the working tree
itself looks cloud-synced.
