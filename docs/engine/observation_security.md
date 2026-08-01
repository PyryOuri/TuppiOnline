# Player-observation security

## Security objective

The clean engine owns all card ownership. An agent receives only an immutable
`PlayerObservation` for its seat, never `DealState`, `MatchState`,
`ExplicitDeal`, or a research result.

This boundary prevents accidental hidden-information leakage through the
formal agent API and gives later search/evaluation code a small object to
audit. It is not an operating-system security sandbox for hostile Python code.

## Private and observable data

The engine keeps these values private during play:

- every opponent's unshown, unplayed cards;
- the complete initial hands;
- current opponent hands;
- stable deal and match-input content hashes;
- private deal validation/replay state; and
- any agent-owned state unrelated to the observing seat's call.

An observation contains only:

- the ruleset and schema identifiers;
- public match/deal references;
- observing seat, team, and partner;
- dealer, forehand, phase, and current actor;
- the observing player's current hand;
- ordered accepted shows, including shown card, declared contract, and the
  rule-derived verbal requirement;
- resolved contract, declarer, and first leader when known;
- completed tricks and the current partial trick;
- team trick totals and current match score;
- legal actions, but only when the observer is the current actor; and
- deal/match terminal flags.

The shown card is public immediately but remains in the owner's private current
hand until it is played. No other card from that hand becomes observable merely
because a show occurred. A card becomes public when its `card_played` action is
accepted.

At the end of a deal, all 52 cards have necessarily appeared in the public play
transcript. That is expected public history, not a premature disclosure. The
public history still does not include a separate initial-hands field.

## Pure observation projection

`observation_for(state, seat)` first validates the private deal state and seat,
then constructs a new frozen, slotted dataclass field-by-field. Collections are
immutable tuples. Cards, plays, shows, completed tricks, enums, and scores are
also immutable value objects.

The observation does not contain:

- a parent pointer to private state;
- a mapping or list view backed by private state;
- a callback or closure that captures private state;
- a generic object payload;
- a private result object; or
- a full-state serializer.

The observer's own hand tuple and public immutable values may safely share
immutable leaf objects with state. Opponent hand tuples are never copied into
or referenced by the observation. Mutating the original input lists after deal
construction cannot mutate engine state or an existing observation.

Observation generation is pure: it has no I/O, randomness, or state mutation.
Calling it repeatedly cannot alter action order or game progression.

## Legal actions disclose only current legality

For a nonacting seat, or after deal completion, `legal_actions` is empty. For
the current actor:

- during showing, the engine exposes only show actions legal under the complete
  private hand and authoritative fallback hierarchy; and
- during trick play, it exposes only cards legal under follow-suit.

This necessarily reveals to the acting player facts already implied by that
player's own hand. It does not enumerate any opponent action.

Ordering is deterministic. Showing uses NOLO before RAMI and then current hand
order. Play actions use current hand order after legal-card filtering. The
engine filters the ordered hand rather than exposing or iterating an unordered
rules set.

Every enumerated action still passes through strict transition validation.
Legal-action enumeration is a convenience for agents, not an authorization to
bypass state validation.

## Agent-call boundary

The protocol is intentionally small:

```python
class Agent(Protocol):
    @property
    def identity(self) -> str: ...

    def choose_action(self, observation: PlayerObservation) -> Action: ...
```

For each turn, `play_active_deal` identifies the current actor, constructs that
actor's observation, calls only that actor's agent, and validates the returned
engine action. It does not pass the runner, transition function closure, or
private state as an argument. A malicious or defective agent cannot select a
different actor, return a card it does not hold, violate follow-suit, or act in
the wrong phase without a typed failure.

Each seat must use a distinct agent object. This prevents an accidental
configuration in which one ordinary stateful object collects all four seats'
private observations. Fixed-script global ordering is checked by a
runner-owned public-action cursor; each fixed-script agent retains only its
own seat-specific actions.

The supplied first-legal agent reads only `legal_actions`. The fixed-script
agent consumes a seat-specific action sequence without inspecting private
state. Neither utility is presented as strategically strong.

## Formal isolation versus hostile-code sandboxing

The guarantee in this phase is object-capability isolation through the formal
interface: a correctly integrated agent has no reference path from its
observation to private hands.

Arbitrary Python executing in the same process is not a hostile-code boundary.
Such code could attempt frame inspection, monkey-patching, module-global
inspection, debugger attachment, filesystem access, or process-memory attacks
outside the `Agent` protocol. Preventing those attacks would require a later
process/container isolation design with a narrow serialized IPC protocol,
resource limits, and explicit trust policy. No network or subprocess agent
transport is added in Phase 2.

Distinct agent objects can still deliberately collude through a module global,
filesystem, or another side channel because they run in one trusted process.
Phase 2 prevents reference leakage and accidental object reuse; it does not
claim process isolation between mutually hostile agents.

Tests described as adversarial in this phase therefore inspect the complete
reachable observation object graph and serialized observation. They establish
that the formal interface contains no full state or hidden-card reference; they
do not claim to sandbox arbitrary native or Python code.

## Public references and private content commitments

Public observations and events carry `match_ref` and `deal_ref`:

- `match_ref` is an explicit caller-provided label;
- `deal_ref` is the deterministic public path
  `<match_ref>/deal:<zero-based-number>`; and
- neither is derived from cards by the engine.

Callers should therefore choose references that contain no sensitive
information.

By contrast, `deal_id` is a SHA-256 digest over the ordered hidden hands and
dealer, and `match_input_id` commits to the ordered deal identities and initial
match context. A content hash can reveal equality and can verify a guessed
candidate input even though it does not directly print the cards. For that
reason these identifiers are kept in explicit full-information inputs,
script-binding metadata, private engine state, and research-private output.
They are intentionally absent from `PlayerObservation`, `PublicEvent`,
`DealResult`, and `MatchResult`.

The public event log has its own `event_log_id`, derived only from already
public event content and public references.

## Serialization boundary

Observation serialization is implemented explicitly field-by-field. The
engine does not serialize full state and then remove selected keys, because
filtering a private representation is brittle and prone to future leakage.

The optional public event-log artifact is similarly built only from typed
public events. It contains shows as they occur and cards only when played. The
research output is a separate format marked:

```text
visibility = research_private
contains_hidden_information = true
```

Research output contains complete initial hands and must be stored, shared,
and analyzed as hidden-information-bearing data. It must never be reused as an
agent observation or public live-game feed.

## Deferred security work

Later phases may add agent processes, search workers, datasets, or distributed
evaluation. They must preserve this projection boundary and add explicit tests
for any new serialized protocol. Untrusted-agent sandboxing, secret storage,
access control, log redaction policy, and network security remain outside the
Phase 2 engine.
