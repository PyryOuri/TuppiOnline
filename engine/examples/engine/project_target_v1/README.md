# Deterministic `project_target_v1` engine examples

These are fully materialized, randomness-free inputs for the clean Phase 2
engine. They are not legacy fixtures and do not import behavior from
`legacy_v9_unverified`.

Match-input files use `tuppi.engine.match_input.v1`. Paired script files use
`tuppi.engine.agent_script.v1` and contain every accepted show and card-play
action. The runner partitions each script by seat before constructing the four
fixed-script agents, while a separate runner-owned cursor preserves and checks
the exact global action order. A successful run therefore proves that every
scripted action was consumed in order through player-specific observations.

Card codes use rank followed by suit, such as `3D` or `AS`. Every valid deal
contains four ordered 13-card hands and a canonical SHA-256 deal identifier.

## Included situations

| Match input | Action script | Expected result |
|---|---|---|
| `valid_one_deal_match.json` | `full_nolo_script.json` | Four NOLO declarations; tricks 0–13; Team 0 wins 28; score 28–0; next dealer 1. |
| `successful_rami_match.json` | `successful_rami_script.json` | Seat 1 declares RAMI and its partnership wins all 13 tricks; Team 1 receives 28; score 0–28. |
| `stolen_rami_match.json` | `stolen_rami_script.json` | Seat 0 declares RAMI and loses 0–13; Team 1 receives 56 stolen-RAMI points and the match ends 0–56. |
| `verbal_fallback_match.json` | `verbal_fallback_script.json` | Seat 0 has no eligible red card, shows black `3C`, and verbally declares RAMI; the derived verbal flag is true. |
| `no_eligible_show_match.json` | `no_eligible_show_script.json` | Seat 1 has no rank 3–9, shows ineligible `2H`, and verbally declares RAMI; tricks 4–9 and score 0–12. |
| `exact_52_match.json` | `exact_52_script.json` | Four deals produce 0–28, reset to 0–0, rebuild to 0–28, then finish exactly 0–52. |

`invalid_duplicate_card_deal.json` intentionally replaces `AS` with a second
`AH` while retaining four 13-card hands. Strict loading fails because the hands
do not partition the standard 52-card deck. Its claimed identifiers are
intentionally not recomputed.

## Run one complete deal

From the repository root:

```bash
python -m tuppi_engine.runner \
  --deal-file examples/engine/project_target_v1/valid_one_deal_match.json \
  --agents scripted,scripted,scripted,scripted \
  --script-file examples/engine/project_target_v1/full_nolo_script.json \
  --output result.json \
  --event-log public-events.json
```

The deal completes after all 13 tricks. The supplied single-deal sequence is
nonterminal, so this command intentionally omits `--require-complete-match`.

## Run the exact-52 match

```bash
python -m tuppi_engine.runner \
  --deal-file examples/engine/project_target_v1/exact_52_match.json \
  --agents scripted,scripted,scripted,scripted \
  --script-file examples/engine/project_target_v1/exact_52_script.json \
  --output exact-52-result.json \
  --event-log exact-52-public-events.json \
  --require-complete-match
```

The four deal totals are `(0,13)`, `(13,0)`, `(0,13)`, and `(1,12)`.
Dealer seats are 0, 1, 2, and 3. The final deal is terminal and therefore has
no following dealer rotation.

## Regenerate and validate

The example-local utility contains the explicit deterministic constructions,
computes canonical identifiers through the engine serialization API, replays
each valid script through the headless runner, checks exact outcomes, and then
writes the canonical JSON files:

```bash
PYTHONPATH=src python examples/engine/project_target_v1/generate_examples.py
```

It uses no RNG and performs no search. The checked-in JSON files—not the
generator's Python object state—are the runner inputs.

## Visibility

Match inputs, fixed scripts, and research results are private research
artifacts: they contain complete hands or future actions. Do not pass them to
agents. The runner passes only immutable player observations to each agent.
The optional event-log output is the privacy-safe public artifact and reveals
cards only through accepted shows and plays.
