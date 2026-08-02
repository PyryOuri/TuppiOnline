# Tuppi research project

This repository contains the frozen Phase 0B legacy harness, the Phase 1
authoritative rules specification, the Phase 2 deterministic clean engine,
the Phase 3 deterministic evaluation framework, the Phase 4 transparent
baseline-agent ladder, and the Phase 5A complete-match evaluation protocol.

Seven boundaries matter:

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

Create an isolated environment and install both packages plus development
dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install '.[dev]'
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
provenance, and a reproducible evaluation protocol. The next phase should build
a sealed promotion bank, then add search or belief modelling on top of the
existing hard-constraint layer, using these agents as rollout policies, opponent
models, and fixed historical baselines. No legacy result is a strength benchmark
unless independently reproduced, and no Phase 4 result is an expert-strength
claim.
