# The frozen-baseline gate

Phase 5B adds an exact solver, a hidden-hand sampler, and a constraint model to a
repository whose earlier phases explicitly disclaimed all three. That is exactly
the situation in which a frozen baseline is easiest to spoil and hardest to notice:
a helper quietly imported into an agent, a threshold nudged while debugging, a
report regenerated with a newer profile. Policy alone catches none of it.

So the gate is mechanical. `tuppi_exact.integrity` runs five checks, and two of
them need no recorded baseline at all - which means they still work on a fresh
clone.

## The five checks

**1. Archive artifacts.** The two frozen legacy files still hash to the values in
`manifests/legacy_v9.json`. No external reference is needed: the manifest *is* the
record, and `archive_manifest_agreement` compares bytes and sizes against it.

**2. Ruleset content.** `configs/rules/project_target_v1.json` still digests to the
recorded value, and `RULESET_ID` / `RULESET_VERSION` still match.

**3. Phase 4 agents.** The behaviour digests in
`reports/phase5a/phase4_frozen_agents.json` still reproduce. This delegates to
`tuppi_match.freeze.verify_snapshot` rather than reimplementing it, so there is one
definition of "the agents have not moved", not two that can drift apart.

**4. Phase 5A artifacts.** Every committed report and the sealed-bank commitment
still hash to the recorded values, the commitment still declares
`role: promotion_sealed` and keeps its `bank_commitment`, `bank_id`, `seed_digest`,
and `usage_rule`, and **no sealed-opening record exists** anywhere under
`reports/`.

**5. Capability containment.** This is the check only Phase 5B needs, and the
reason this module exists rather than reusing `tuppi-match freeze --verify` alone.
It asserts two things:

- every frozen agent still declares `search`, `belief_model`, `endgame_solver`,
  `hidden_hand_sampling`, `learning`, and `rollout_budget` as `null`;
- **no earlier package references `tuppi_exact`.** The source of `tuppi_rules`,
  `tuppi_engine`, `tuppi_eval`, `tuppi_agents`, `tuppi_legacy`, and `tuppi_match` is
  parsed and the check fails on any mention.

If a Phase 4 module could import the solver, every Phase 4 and Phase 5A result
would become retroactively search-assisted and no earlier claim would still mean
what it said. Check 5 makes that impossible rather than merely discouraged.

## Using it

```bash
# Checks that need no recorded baseline, plus a working-tree warning.
python -m tuppi_exact.runner integrity --report

# Verify everything against the committed baseline.
python -m tuppi_exact.runner integrity --verify reports/phase5b/frozen_baseline.json

# Rewrite the baseline. Only correct when a change was *intended*.
python -m tuppi_exact.runner integrity --output reports/phase5b/frozen_baseline.json
```

`--verify` exits `3` and prints one `DRIFT:` line per problem. Drift is drift: the
committed baseline is not a cache to be refreshed when it disagrees.

## The working-tree warning

`working_tree_location()` reports whether the repository sits under a
cloud-synced path (`Documents`, `Library/Mobile Documents`, `iCloud Drive`,
`Dropbox`, `Google Drive`, `OneDrive`).

It is **reported, never digested**, so a committed baseline stays
machine-independent. The reason it is reported at all is concrete rather than
hygienic: a cloud-synced working tree was the reproducible cause of a stalled CLI
subprocess test, and relocating the tree to a plain local path is what fixed it.
See `docs/exact/phase5b_results.md` for the before-and-after timings.

## What the baseline covers, and what it cannot

The recorded baseline pins content digests and behaviour digests. It cannot detect
a change that alters neither - a comment, a docstring, a refactor with identical
behaviour. That is by design: the baseline protects *behaviour and content*, and a
behaviour-preserving refactor is not drift.

It also does not pin the Phase 5B code itself. Phase 5B is the phase under
construction; freezing it would freeze work in progress. Its results are pinned by
the schemas in `schemas/exact/` and the reports in `reports/phase5b/`, and its
correctness by `tests/exact/`.
