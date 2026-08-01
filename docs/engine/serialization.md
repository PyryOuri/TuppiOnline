# Engine serialization

## Goals

Serialization is versioned, strict, canonical, and separated by visibility.
It supports deterministic replay from complete explicit inputs without making
stdout or presentation text authoritative.

The Python serializers construct each output explicitly. They do not serialize
private engine state generically, and public output is not produced by deleting
fields from a research-private record.

## Versioned formats

| Value | Schema/version identifier | Visibility |
| --- | --- | --- |
| Explicit deal | `tuppi.engine.explicit_deal.v1` | Full information input |
| Explicit match input | `tuppi.engine.match_input.v1` | Full information input |
| Fixed agent script | `tuppi.engine.agent_script.v1` | Controlled execution input |
| Player observation | `tuppi.engine.player_observation.v1` | One-player private view |
| Public event | `tuppi.engine.public_event.v1` | Public |
| Public event log | `tuppi.engine.public_event_log.v1` | Public |
| Deal result | `tuppi.engine.deal_result.v1` | Public terminal history |
| Match result | `tuppi.engine.match_result.v1` | Public terminal history |
| Research run result | `tuppi.engine.research_result.v1` | Research-private, full information |

All rule-bearing documents identify `project_target_v1`. Card strings use
`project_target_v1_suit_major_hdcs_rank_2_to_ace` and canonical uppercase codes
such as `2H`, `10D`, `JC`, and `AS`.

## Explicit deal input

An explicit deal records:

- schema, ruleset, and card-encoding identifiers;
- dealer;
- four ordered hands of exactly 13 cards; and
- a claimed canonical `deal_id`.

Parsing validates that the hands partition the standard 52-card deck, all
cards use canonical spelling, and the claimed identifier exactly matches the
materialized content. Within-hand order is preserved; it affects deterministic
first-legal action order and is part of deal identity.

The deal identity is:

```text
sha256(canonical_json({
  schema_version: "tuppi.engine.deal_identity.v1",
  ruleset_id,
  card_encoding,
  dealer,
  ordered hands
}))
```

It does not depend on a source path, output path, logging verbosity, agent, or
Python's process-randomized `hash()`.

## Explicit match input

The runner's `--deal-file` consumes one `tuppi.engine.match_input.v1` object.
It contains:

- a public `match_ref`;
- initial nonterminal one-sided score;
- initial dealer;
- one or more complete explicit deals; and
- a claimed `match_input_id`.

Deal dealers must rotate exactly from the initial dealer according to their
position in the supplied sequence. The parser rejects rather than rewrites a
mismatch. Runtime execution additionally rejects any supplied deal after the
match has already reached 52 or more.

`match_input_id` is a SHA-256 commitment over the schema identity, ruleset,
initial score, initial dealer, and ordered deal IDs. `match_ref` is deliberately
excluded, allowing the same game content to be labeled for different runs
without changing content identity.

A fixed script records the same `match_input_id`. Loading rejects a script
bound to different explicit content. Each action has an exact type-specific
field set; show actions carry seat, shown card, and contract, while play actions
carry seat and card.

## Strict input parsing

`strict_json_loads` and the format-specific parsers reject:

- duplicate object keys;
- malformed JSON and non-finite numeric constants;
- missing fields and unknown fields;
- unsupported schema, ruleset, or encoding identifiers;
- noncanonical lowercase or padded card strings;
- malformed seats, scores, contracts, hands, or action types;
- duplicate or missing cards;
- terminal initial scores;
- mismatched claimed content hashes; and
- empty deal sequences or scripts.

The file loader requires a regular file and rejects `-`, device files such as
`/dev/stdin`, and FIFO-style inputs; stdin is not an input source. Semantic
engine validation remains active after parsing, so a structurally valid action
can still be rejected for wrong actor, phase, card ownership, show hierarchy,
or follow-suit.

## Canonical JSON

Canonical bytes are UTF-8 JSON produced with:

- lexicographically sorted object keys;
- compact separators without insignificant whitespace;
- explicit enum values;
- canonical card codes;
- `ensure_ascii=False`;
- non-finite numbers forbidden; and
- no object repr, address, timestamp, random identifier, or Python `hash()`.

`canonical_json_bytes` returns bytes and `canonical_json_text` decodes those
same bytes. File artifacts add one final newline. Serializing the same value
repeatedly is byte-identical.

## Public events

Events are frozen typed records with:

- schema and ruleset identifiers;
- a match-global monotonic `event_index`;
- public `match_ref` and `deal_ref`;
- a closed `event_type`; and
- the corresponding typed public payload.

The canonical order during a deal is:

1. `deal_started`;
2. one or more `show_accepted` events;
3. `contract_resolved` and first `trick_started`;
4. four `card_played` events per trick;
5. `trick_completed`, followed by `trick_started` when another trick remains;
6. `deal_completed`;
7. `match_score_changed`; and
8. either `dealer_rotated` or `match_completed`.

The aggregate match event log starts at zero and is contiguous. A deal-result
event slice may start at a later match index. `event_log_id` hashes the public
schema identity, public reference, and canonical event list.

Deal state and public result constructors independently reconstruct the entire
expected event sequence and require exact equality. This binds shows, plays,
trick winners, score changes, and terminal/dealer events to accepted state
rather than trusting a caller-supplied frozen event tuple. A public result also
checks that each shown card is later played by the same seat.

No `deal_started` event contains hands or a private deal hash. A shown card is
serialized when its show is accepted, and every played card is serialized only
when its play is accepted.

## Public references versus private hashes

`match_ref` and `deal_ref` are public labels. `deal_ref` is derived only from
the caller's match label and zero-based deal number. They are used to correlate
public events without committing the event stream to hidden hands. Callers are
responsible for avoiding confidential text in `match_ref`.

`deal_id` and `match_input_id` are different: they are cryptographic content
commitments involving hidden hands. Although SHA-256 does not print those
hands, a digest reveals equality and supports verification of a candidate
deal. They are therefore absent from public events, observations, deal
results, and match results.

The identifiers appear only where full information is already authorized:

- explicit deal/match inputs;
- private engine state;
- fixed-script binding metadata; and
- research-private results.

## Public and research outputs

A public deal result contains ordered shows, all 13 completed tricks, outcome,
score transition, dealer information, and its public event slice. A terminal
public match result aggregates public deal results and the public match event
history. Neither contains initial hands or a private deal/input content hash.

The CLI's required `--output` is a `tuppi.engine.research_result.v1` artifact.
It includes:

- `visibility: "research_private"`;
- `contains_hidden_information: true`;
- canonical match-input identity;
- agent identities;
- every complete initial deal;
- public results and events; and
- terminal or finite-sequence status.

This artifact must not be published as a live public log or passed to an agent.

`--event-log` optionally writes a separate
`tuppi.engine.public_event_log.v1` artifact containing only public events. It is
the appropriate machine-readable public transcript.

## Output writing and failure behavior

The runner materializes research and optional public data, validates every
destination, and stages every artifact before replacing any destination. Each
temporary file is flushed and synced, then atomically replaced. A missing
second parent therefore cannot leave only the first new output behind, and a
failed individual write cannot truncate an existing destination.

The two optional destinations are not a multi-file transaction: a failure of
the second atomic replacement may leave the first new artifact present. Their
content hashes and schema identifiers permit independent verification.

Output parent directories must already exist. Existing destinations must be
regular files, not symlinks or device files. `-` is rejected for output, so
stdout is never the authoritative record. Human diagnostics go only to stderr
and do not affect canonical content. Output and event-log paths must differ,
and neither may alias the deal or script input, including an existing hard
link.

## Deterministic execution contract

For identical explicit match input and fresh agents with identical scripts or
first-legal behavior, the accepted actions, event stream, results, and
canonical bytes are identical. Changing the output path or verbosity does not
change execution content.

The engine transition core has no RNG. If random deal generation is added in a
later phase, it must remain outside the core, require an explicit seed,
materialize the complete deal first, and record the resulting explicit input.

Serialization formats are versioned rather than silently accepting an evolved
shape. A behavioral or incompatible representation change requires a new
schema/version identifier and corresponding migration or reader support.
