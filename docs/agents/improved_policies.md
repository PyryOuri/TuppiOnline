# The improved partner-aware policies

Two policies sit above the frozen Phase 4 ladder without joining it.  They are
the first agents in this repository measured to play better than
`partner_aware_v1`, and they are the reason `docs/agents/baseline_profiles.md`
remains true: neither is a registered Phase 4 profile, so no earlier result
becomes retroactively different.

| Policy | Module | Change | Measured, paired |
| --- | --- | --- | ---: |
| `partner_aware_lead_v2` | `void_lead.py` | NOLO: lead the shortest suit, lowest card within it | **-0.69 tricks, +13.9 pp** |
| | | RAMI: lead the suit worth the most tricks if played out | **+0.36 tricks, +8.2 pp** |
| `partner_aware_discard_v3` | `nolo_discard.py` | NOLO discards priced by the exact conditioned ducking law instead of the legacy rank table | **-0.338 tricks/deal**, `[-0.392, -0.284]`, z = -12.51 |

All three changes are **dominant**: still ahead when the opponents adopt them
(+12.2 pp, +5.0 pp, and -0.296 tricks respectively).  Fewer tricks is better
under NOLO.

`partner_aware_discard_v3` extends `partner_aware_lead_v2`; the stack is
`partner_aware_v1` -> `lead_v2` -> `discard_v3`, and only leads and the NOLO
discard branch differ from the base.  **Every figure above is conditional on
`partner_aware_v1`'s other following play**, which is unchanged, and on the
measurement conditions recorded with each result.  Neither policy is
expert-validated.

## Why they are not Phase 4 profiles

`docs/agents/architecture.md` records that every Phase 4 agent specification
carries `search`, `belief_model`, `endgame_solver`, `hidden_hand_sampling`,
`learning` and `rollout_budget` as `null`, and that the frozen `agent_id` of each
rung is what every Phase 4, 5 and 6 result is quoted against.  Adding a rung
would change the reference population underneath results that have already been
published, so `void_lead.py` states the constraint directly: "registering a
profile here would break that baseline."

They also stay out of `rule_catalogue`.  Every rule id in a scored candidate must
resolve there, and the catalogue's provenance constraints are tied to the frozen
profiles - `FORBIDDEN_PHASE4_PROVENANCE` forbids exactly the two labels a
simulation-validated rule would want.  The improved layers are therefore
expressed as score *components* with reason codes (`void_lead_shortest_suit`,
`establish_longest_paying_suit`), which carries the same explanation into the
diagnostics channel without editing a structure that sits beside the baseline.

## Two identity conventions, and why both exist

Both modules stamp their runtime policies with a *prefixed* string:

```text
partner_aware_lead_v2:agent:sha256:d8b426f1…      # d8b4… is partner_aware_v1
```

That names the base profile, not the improved behaviour.  Changing a lead rule
leaves it untouched, so it cannot serve as the identity of a generated artifact -
which matters as soon as a corpus, an evaluation record or a report has to say
which policy played and be reproducible from that statement.

`improved_registry.py` mints the real thing: a content address over the improved
policy's *own* behavioural content - the base profile's identity, the ordered
tuple of behavioural layers, and each layer's materially behavioural parameters.

| Policy | Content-addressed identity |
| --- | --- |
| `partner_aware_lead_v2` | `agent:sha256:252fe227b01900e3c1d94822179adee07a64e3a3eb761a529a425f39b95d435d` |
| `partner_aware_discard_v3` | `agent:sha256:4b52fd908698de131ab1c9c4562b37da8da4733b8005b0e935fbd15339a17634` |

The properties are the ones `HeuristicProfile` already guarantees for profiles,
and each is asserted in `tests/agents/test_improved_registry.py`:

- a changed layer parameter, an added layer, or a reordered stack mints a new
  identity;
- a reworded description does not, because `AgentSpecification.identity_data`
  excludes the description;
- the chain is transitive - `discard_v3`'s address moves if `lead_v2`'s does;
- no improved identity can collide with a frozen Phase 4 one, and
  `STRATEGIC_PROFILE_KEYS` is unchanged.

**Both conventions are live on purpose.** The prefixed string is read by the
private-alpha server, `schemas/network/*`, `ReferencePolicy.swift` and persisted
room state, and `docs/valuation/nolo_ducking_results.md` records that renaming it
carelessly breaks restart recovery (a persisted room stores its
`ai_profile_key`, and `_construct_ai_agents` then raises on boot).  Changing it
is the "four-surface profile change" that document defers.  Until then:

> Use `improved_registry.construct_improved_agent` for anything that writes a
> record that must be citable.  Use the existing `void_lead` / `nolo_discard`
> constructors for the live runtime.

`tests/agents/test_improved_registry.py` asserts the two paths select
byte-identical actions over complete matches, so the choice of constructor
changes the recorded identity and nothing else.

## Which one is the reference

`partner_aware_lead_v2` is the live AI, the analysis reference, and - by decision
D4 of `docs/database/phase7_charter.md` - the Phase 7 corpus reference policy.
`improved_registry.CORPUS_REFERENCE_PROFILE_KEY` is the single place that is
recorded, so a change of reference is one edit with one identity consequence.

`partner_aware_discard_v3` is deliberately **not** the reference.  It is
committed and registered, and it enters the corpus through the population
stratum, so the corpus can measure whether it should be promoted rather than
presupposing it.  Its own results document is explicit that it is not shipped and
that its measurement covers forced-NOLO deals, one seed, one contract and one
starting score.

## Provenance of the evidence, and a coverage gap

The measurements above come from `docs/valuation/`, which documents
`src/tuppi_valuation/` - **an untracked package that is not part of this
commit.** Read `docs/valuation/handoff.md` for the open problems, the failed
hypotheses, and in particular §3.1, which establishes that inference fitted on a
deterministic policy corpus measures that policy's determinism rather than the
game.

One gap is worth stating plainly: `tests/agents/test_nolo_discard.py` cross-checks
the ducking maths duplicated into `nolo_discard.py` against the canonical
`tuppi_valuation.suits` implementation, and it is **not committed**, because it
imports that untracked package.  The committed coverage of `nolo_discard.py` is
therefore behavioural rather than mathematical:
`tests/agents/test_improved_registry.py` plays complete matches with it and
requires it to differ from `lead_v2` and to agree with its own existing
constructor.  When `tuppi_valuation` lands, that cross-check should land with it.

`void_lead.py` is also one of the files the `tuppi_exact` integrity text scan
reports on: it names `tuppi_exact` in a comment explaining that it must not
import the exact layer, and the scan reads raw module text.  There is no import
and the boundary holds; committing the file does not change that pre-existing
report either way.
