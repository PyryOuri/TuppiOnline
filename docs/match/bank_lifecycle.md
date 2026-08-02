# Fixture-bank lifecycle

A bank is a named family of independent match streams plus the role it may be
used in. The role is enforced at execution time and recorded in every resolved
manifest and every report; it is not a comment.

## The three roles

### `development`

Visible, debuggable, reusable without limit. Used while building the harness and
while diagnosing a surprising result.

**It supports no promotion claim of any kind.** A report produced on a
development bank says so in its `interpretation.bank_role` field.

### `calibration`

Run once, to estimate the quantities a future experiment needs to be designed
properly:

- the match-length distribution and therefore the safety cap;
- paired variance, and therefore the sample size;
- complementary-leg correlation, and therefore how much deal luck the duplicate
  design removes;
- censoring probability;
- reset frequency and contract frequencies;
- execution cost.

It may be inspected after execution - that is the point of it. What it must not
become is a tuning loop: adjusting an agent and re-measuring on the same
calibration bank until the number improves is exactly the failure mode the three
roles exist to prevent. **A changed profile is a new agent identity and belongs
to a later experiment.**

### `promotion_sealed`

Created only after the agents and the protocol are frozen. This is the only role
for which `supports_promotion` is true.

Handling rules:

- **Seed material lives outside the repository.** `write_sealed_seed` refuses a
  path inside the repository tree, and so does `open_sealed_bank`.
- **The repository stores a commitment, not the fixtures.** A sealed commitment
  records the bank identity, the role, the stream count, and a digest over the
  first deals of the first streams. `sealed_commitment()` never returns the
  seed, and a test asserts the seed string is absent from its output.
- **Opening is explicit and recorded.** `open_sealed_bank` requires a written
  reason of at least eight characters and returns an opening record carrying the
  reason, the seed digest, the seed source path, and the bank commitment. There
  is no way to open it silently.
- **Ordinary work is refused.** `require_not_sealed(bank, action=...)` raises
  `SealedBankError`, and `tuppi_match.run` refuses a sealed manifest unless the
  caller passes `allow_sealed=True`.
- **Fixtures never reach an agent.** The engine label in every observation is
  `cm-<leg>-<ordinal>`, derived from an ordinal and never from the stream, the
  bank, or the seed.

The design is deliberately simple and local. There is no remote sealed-evaluation
service, and none is planned. This protects against opening the bank by
accident, not against an operator who has decided to cheat.

## Command line

```bash
# Create: writes the seed outside the repository, commits only the commitment
python -m tuppi_match.runner seal --action create \
  --seed-file ~/.tuppi/phase5a_sealed_seed.json \
  --seed "<at least 16 characters of seed material>" \
  --streams 512 \
  --output reports/phase5a/sealed_commitment.json

# Open: requires a reason and produces a record
python -m tuppi_match.runner seal --action open \
  --seed-file ~/.tuppi/phase5a_sealed_seed.json \
  --reason "Phase 5B promotion evaluation of the first search agent" \
  --output reports/phase5b/sealed_opening_record.json
```

The seed may also be supplied through the `TUPPI_SEALED_SEED_FILE` environment
variable.

## Which bank answered which question in Phase 5A

| Bank | Role | Streams | Used for |
| --- | --- | --- | --- |
| `phase5a_development_v1` | development | 64 | harness debugging and the test suite |
| `phase5a_calibration_v1` | calibration | 512 | the 256-pair ladder and ablation comparisons |
| `phase5a_score_state_diagnostics_v1` | development | 128 | secondary conditional match-equity diagnostics |
| `phase5a_promotion_sealed_v1` | promotion_sealed | 512 | **unopened**; reserved for Phase 5B |

Every Phase 5A number in this repository comes from a calibration or development
bank. None of them is a promotion claim, and none of them designates a champion.
