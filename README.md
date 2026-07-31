# Tuppi research project

This repository contains the frozen Phase 0B legacy harness and the Phase 1
authoritative rules specification. It does not yet contain the future trusted
game engine or evaluation framework.

Four boundaries matter:

1. `Archive/` contains byte-for-byte frozen historical artifacts.
2. `src/tuppi_legacy/` verifies and executes the old emulator through an
   external, finite, all-AI adapter.
3. `project_target_v1` is the authoritative future ruleset. Its pure executable
   reference is in `src/tuppi_rules/`; it is not a complete game engine.
4. The future clean engine will be a separate implementation whose normative
   tests are independent of legacy characterization.

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

## Headless execution

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

`src/tuppi_rules/` is an executable specification, not a playable engine. The
next phase should build a clean state machine around player-specific immutable
observations and strict actions. AI strength work must wait until that engine
and a controlled evaluation framework are complete; no legacy result is a
strength benchmark unless independently reproduced.
