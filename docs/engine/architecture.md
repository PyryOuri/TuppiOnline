# Clean engine architecture

## Status and scope

`tuppi_engine` is the deterministic, headless execution layer for the
authoritative project ruleset `project_target_v1`. It builds on the pure rule
functions in `tuppi_rules`; it does not use the archived prototype or
`tuppi_legacy` as a rules oracle.

The engine is deliberately about correctness, state ownership, privacy-safe
agent calls, and reproducible execution. The only supplied agents are a
first-legal-action agent and a fixed-script agent. They are deterministic test
utilities, not strategic baselines.

## Dependency direction

The intended dependency direction is:

```text
CLI runner
  -> serialization, agents, match coordinator
       -> observations, explicit deals, transitions, results
            -> actions, private state, public events
                 -> tuppi_rules
```

No module in this package imports `tuppi_legacy`. The transition core performs
no file I/O, printing, networking, GUI work, or random sampling.

## Modules

| Module | Responsibility |
| --- | --- |
| `actions.py` | Frozen engine `ShowAction` and `PlayCardAction` values. |
| `deal.py` | Validation and materialization of ordered explicit deals, stable private deal identity, and initial deal state. |
| `state.py` | Full private `DealState`, completed-trick records, explicit phases, and defensive cross-field invariants. |
| `transitions.py` | Strict pure showing and card-play transitions, scoring, result construction, and public-event emission. |
| `observations.py` | Pure projection from private deal state to one immutable player observation and stable legal-action enumeration. |
| `match.py` | Match-level score/dealer coordination, globally ordered public events, agent calls, and terminal match results. |
| `events.py` | Frozen public event types and closed, typed payload variants. |
| `event_builder.py` | Sole canonical reconstruction of events from accepted public deal fields. |
| `identity.py` | Shared canonical private deal-content identity construction. |
| `results.py` | Separate public deal/match results and research-private full-information results. |
| `serialization.py` | Strict versioned JSON input, canonical output, content identities, and atomic file writes. |
| `validation.py` | Shared schema-exact validation of public references and stable digests. |
| `agents.py` | Minimal agent protocol and deterministic non-strategic utilities. |
| `runner.py` | Finite CLI execution over an explicit deal sequence. |
| `errors.py` | Typed construction, action, phase, state, agent, serialization, and sequence failures. |

## State ownership

`DealState` is the authoritative private state for one active or just-completed
deal. It owns:

- the complete ordered initial hands;
- the four current hands;
- showing, current-trick, and completed-trick histories;
- contract, declarer, leaders, trick totals, and scoring fields;
- the deal's slice of the immutable public event history; and
- a private content-derived `deal_id`.

`MatchState` owns the active private deal, completed research results, current
score and dealer, and the aggregate public event history. Consequently,
`MatchState`, `DealState`, `ExplicitDeal`, `ResearchDealResult`, and
`ResearchRunResult` are trusted engine/research objects and must never be
passed to an agent.

State records are frozen dataclasses using tuples for collections. Each new
state is constructed as a replacement value rather than mutated in place.
Cards, scores, rule show records, tricks, events, and results are likewise
immutable value objects. `validate_deal_state` and `validate_match_state`
defensively recheck public transition boundaries, including reconstructed hand
contents and follow-suit legality.

## Core API

A match is created, supplied one explicit deal at a time, and advanced only by
validated actions:

```python
state = create_match(
    initial_score=MatchScore(0, 0),
    initial_dealer=0,
    match_ref="experiment-001",
)
state = begin_explicit_deal(state, explicit_deal)

while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
    actor = state.current_actor
    observation = match_observation_for(state, actor)
    action = agents[actor].choose_action(observation)
    state = apply_match_action(state, action)
```

`play_active_deal` performs this finite loop for exactly one active deal. It
constructs a `PlayerObservation` for only the current actor, calls only that
seat's agent, and sends the returned action back through the same strict
transition boundary. A safety bound rejects any execution exceeding the
maximum four show actions plus 52 card plays.

The runner requires four distinct agent objects. Reusing one stateful object
for multiple seats would let it accumulate several private observations, so
that configuration is rejected. Fixed scripts remain seat-specific inside
each agent; a runner-owned cursor separately verifies exact global action
order without placing opponent scripts in an agent object.

`begin_explicit_deal` accepts only the dealer required by the current match
state. A mismatch raises `DealSequenceError`; the coordinator never rewrites
the supplied dealer. After a nonterminal deal, the authoritative next dealer
is stored. A terminal match retains the final deal's dealer and accepts no
additional deal or action.

## Rules integration

The engine delegates rule decisions to `tuppi_rules`, including:

- initial-hand and seat validation;
- show-card fallback validation and derived verbal declarations;
- showing resolution and first-leader selection;
- legal cards, follow-suit validation, and trick winners;
- completed-deal validation;
- NOLO and RAMI scoring; and
- rising-score transitions, terminal detection, and dealer rotation.

Engine state retains additional execution context, but it does not duplicate a
second configurable rules implementation. Errors from `tuppi_rules` are
translated into typed engine failures at action and construction boundaries.

## Strict rejection

The engine never repairs, clamps, substitutes, or defaults an invalid action.
It rejects, among other cases:

- an action for the wrong seat;
- the wrong action type for the current phase;
- a card absent from the acting hand;
- an illegal show under the fallback hierarchy;
- failure to follow suit;
- an action after deal or match completion;
- a new deal while another deal is active;
- a deal whose dealer disagrees with match progression; and
- malformed or internally inconsistent state.

Wrong-actor, wrong-phase, terminal-state, invalid-action, deal-sequence, and
state-invariant errors remain distinguishable by type. The original rules
exception is retained as an exception cause where useful.

## Determinism model

The transition core contains no random number generator or clock access. Deal
construction requires all 52 cards and the dealer to be materialized before
play. Within-hand order is preserved and is part of private deal identity.

Legal action enumeration is stable:

- show contracts are considered in the documented order NOLO, then RAMI;
- cards retain their current hand order; and
- play actions retain current hand order after follow-suit filtering.

The engine never relies on `frozenset` iteration for agent-visible action
ordering. First-legal execution is therefore deterministic. Fixed scripts are
bound to the canonical match input, retain exact global order, and have
deterministic identities. Repeated
runs require fresh agent instances because a fixed-script agent consumes its
own cursor; that cursor is agent-owned and never part of engine state.

Serialization uses canonical UTF-8 JSON, and output paths and verbosity are
excluded from gameplay content. Verbosity affects only diagnostic text on
standard error.

## Headless runner

The CLI consumes a strict `tuppi.engine.match_input.v1` document through
`--deal-file`. Despite the option's singular name, the document contains one
or more fully explicit deals, so the same command supports a single deal or a
finite deal sequence.

For deterministic first-legal execution:

```text
python -m tuppi_engine.runner \
  --deal-file path/to/match_input.json \
  --agents first-legal,first-legal,first-legal,first-legal \
  --output path/to/research_result.json \
  --event-log path/to/public_events.json
```

For a scripted execution, use four `scripted` agents and provide a strict
script document:

```text
python -m tuppi_engine.runner \
  --deal-file path/to/match_input.json \
  --agents scripted,scripted,scripted,scripted \
  --script-file path/to/actions.json \
  --output path/to/research_result.json \
  --event-log path/to/public_events.json \
  --require-complete-match
```

The runner never reads stdin and does not use stdout as an authoritative
artifact. It has no GUI or network dependency. Invalid configuration or
execution returns a nonzero status.

## Intentionally deferred

This phase does not provide:

- strategic baseline or legacy agents;
- search, CFR, neural models, reinforcement learning, or belief models;
- random dealing in the core;
- duplicate-deal or population evaluation;
- self-play training or champion promotion;
- coaching or human input;
- GUI or network play; or
- an operating-system sandbox for untrusted agent code.

Those features must build on the observation and deterministic-execution
boundaries rather than bypassing them.
