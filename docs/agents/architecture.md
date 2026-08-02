# Phase 4 baseline-agent architecture

`src/tuppi_agents/` is a ladder of deterministic, observation-only Tuppi agents
for `project_target_v1`. Its purpose is a **reproducible reference
population**, not a strong player. Nothing here is expert strategy, and nothing
here is tuned.

## The observation-only boundary

A Phase 4 policy receives exactly one thing: a frozen
`tuppi_engine.PlayerObservation`. It never receives, and cannot reach:

- engine state (`DealState`, `MatchState`) or any mutable reference into it,
- the initial deal or any other seat's hand,
- a research-private result,
- a private fixture identity or match-stream identity,
- a deal identifier derived from hidden state,
- the evaluator object or an event writer.

`tuppi_agents.protocol.RuleBasedPolicy.__init__` takes only an immutable agent
identity and an immutable profile. `tests/agents/test_architecture.py` parses
every module and fails if any of them imports `random`, `secrets`, `numpy`,
`torch`, `tensorflow`, `jax`, `sklearn`, `scipy`, or `tuppi_legacy`, or reads an
engine-private attribute such as `initial_hands`, `hands`, `active_deal`, or
`deal_id`.

The Phase 4 strategic policies are deterministic and take no seed. The seeded
random legal fixture stays where it belongs, in Phase 3, and is exposed here
only as a protocol control.

## Layers

```text
observation
  -> ordering.py          versioned canonical action order + one tie-break
  -> features.py          hand, showing, and deal/match context
     trick_context.py     current-trick context
     public_inference.py  hard public constraints only
  -> showing.py           legacy-derived and simple showing policies
     reactive.py          rung 2 trick play
     counting.py          rung 3 = reactive + hard inference
     partner_aware.py     rung 4 = counting + partnership rules
     match_aware.py       rung 5 = partner-aware + rising-score rules
     legacy_port.py       rung 1, a separate faithful port
  -> action_scoring.py    lexicographic ranking of every legal action
  -> diagnostics.py       optional, privacy-safe explanation
  -> action
```

Each rung is a strictly larger capability set than the one below, and every
addition enters as a *new named score component* rather than a rewrite. That is
what makes the ablations in `docs/agents/phase4_evaluation.md` structural rather
than parametric.

## Deterministic action ordering and tie-breaking

Two orderings exist and both are versioned:

| Identifier | Use |
| --- | --- |
| `tuppi.agents.engine_legal_action_order.v1` | The engine's own stable `legal_actions` order. Position in that tuple is the only tie-break any policy uses. |
| `lowest_engine_legal_action_index_v1` | The tie-break itself: among equal score vectors the lowest engine index wins. |
| `legacy_v9_suit_precedence_shdc_v1` | Spades, hearts, diamonds, clubs. Not a tie-break: `legacy_heuristic_port_v1` folds it into its score vector so that the port reproduces the archived `min`/`max` selections. |
| `project_target_v1_suit_order_hdcs_v1` | Hearts, diamonds, clubs, spades. Used by the simple showing profile's card choice. |

No policy iterates a `set`, relies on dictionary insertion order arising from
incidental construction, compares object identity, or reads the locale. Where a
suit tie must be broken, the ordering is named and versioned.

Changing logging, diagnostics, the output location, or evaluator metadata cannot
change a selected action. `tests/agents/test_conformance.py` proves this for
every registered agent by replaying the same deal under two different
`match_ref` values and by rebuilding the observation an arbitrary number of
times.

## Scoring instead of nested conditionals

`action_scoring.py` gives every policy the same shape:

1. score **every** legal action into a fixed-length named score vector;
2. take the lexicographic maximum;
3. break ties by the lowest engine action index.

Invariants enforced in code and in property tests:

- every legal action appears in the ranking exactly once;
- all candidates in one decision share one component layout;
- the selected index *is* the deterministic maximum;
- every candidate cites at least one catalogued rule.

Component **order** is the rule priority. A magnitude only matters inside its own
component, which is why Phase 4 exposes exactly one numeric play weight and
expresses everything else as component order or as an on/off rule. That keeps the
framework honest and small: it is not a general strategy language.

## Information-set invariance

The central conformance property is that behaviour depends on the observation
and nothing else. `tests/agents/test_conformance.py` and
`tests/agents/test_properties.py` construct **different full states that yield
an identical observation** by swapping one unplayed, unshown card between two
hidden seats *within a suit*. That preserves every seat's suit counts, so every
past follow-suit decision stays legal and the public history replays exactly,
while the content-derived `deal_id` differs. The tests then require:

- the identical selected action,
- the identical diagnostics record,
- no dependence on the hidden deal identifier, evaluator metadata, output path,
  or observation construction count,
- no mutation of the observation or of engine state.

## Diagnostics as a separate trusted channel

`choose_action` is the engine-facing method and never builds a diagnostics
record. `decide(observation, diagnostics=True)` returns the same action plus a
`DecisionDiagnostics`. Both paths compute the identical ranking, so switching
diagnostics on cannot change play - asserted for every agent over a complete
deal.

A diagnostics record may name only the acting seat's own legal actions, because
those *are* the decision. It never contains another seat's card, the full own
hand, an engine object, an explicit deal, a hidden-state-derived deal
identifier, or evaluator-private data. The observation digest is a one-way
SHA-256 commitment used to prove two decisions came from the identical
observation. Sentinel tests plant recognisable cards in the other three hands
and fail if any of them appears in the serialised record.

`DiagnosticsRecordingAgent` is the explicit wrapper for examples and the
diagnostics-overhead measurement. The evaluator never uses it.

## Identity

A profile is content-addressed over its behavioural content only: family,
version, showing policy, parameters, enabled and disabled rules, capability
switches, partner convention, and show tie-break. The description is explicitly
excluded, so re-wording a description cannot change identity, while changing a
threshold does - and therefore changes the agent ID too.

Every Phase 4 agent specification records `search`, `belief_model`,
`endgame_solver`, `hidden_hand_sampling`, `learning`, and `rollout_budget` as
`null`. They are null on purpose: a later phase that adds any of them must mint
a new agent identity rather than silently reuse a Phase 4 one.

## How these agents may later serve search and learning

The layering is deliberate. A Phase 5 search can use:

- `public_inference.PublicInference` as the *hard constraint set* that any
  determinization or belief model must respect - a sampler that contradicts a
  proven void is wrong by construction;
- any rung as a **rollout policy**: the ladder adds about 0.2 ms per action over
  a first-legal control, and the engine's own revalidation dominates the cost;
- any rung as a **fixed historical baseline** with a frozen agent ID;
- `partner_aware_v1` or `match_aware_v1` as an **opponent model** whose rules are
  written down and citable;
- the diagnostics channel as a **label source** for supervised experiments.

What Phase 4 deliberately does not provide: PIMC, determinization rollouts,
Monte Carlo search, ISMCTS, POMCP, CFR, alpha-beta, endgame solving,
hidden-hand sampling, probabilistic belief models, particle filters, neural
policies or values, reinforcement learning, self-play, population training,
exploiters, a GUI, network play, or a human-input loop.
