# Hypothetical continuation states

A sampled assignment is only useful if something can be *played* on it.
`hypothetical_continuation(observation, assignment)` turns one observation plus one
sampled assignment into a complete `tuppi_engine.DealState` - the same type the
engine uses for a dealt deal, at the same decision point, with the same public
history.

## The construction takes the long route deliberately

It rebuilds the four initial 13-card hands and then **replays the entire public
action history through the ordinary engine transitions**. Nothing is stitched
together by hand; no invariant is asserted locally.

That choice is what makes the sampler's soundness *externally* verified:

- an assignment that violates a proven void produces a replayed follow-suit
  violation, and the engine rejects it;
- an assignment that contradicts a public show action makes the engine's derived
  `verbal_required` disagree with the stored value, and the engine rejects it;
- an assignment that misplaces even one card fails the state's own hand-history
  reconciliation.

So the engine is the referee for the constraint model. An unsound model cannot
quietly produce plausible-looking hypotheticals; it produces exceptions.

Both rejections are tested as *negative controls* in
`tests/exact/test_continuation.py`, by taking a genuinely feasible sample and
forcing one violating card into a seat:

```text
show-exclusion violation -> InvalidActionError: illegal show action: shown card is
                            not allowed by the authoritative fallback hierarchy
void violation           -> InvalidActionError: illegal card play: player must
                            follow the led suit when possible
```

The first of those is the reason the show-derived exclusion in
`docs/exact/constraint_model.md` is **necessary rather than merely nice**: without
it the sampler proposes assignments the engine refuses, and continuation
construction fails outright.

## Hand order, and why it is not cosmetic

The engine derives legal-action order from the order of cards in a hand, and Phase
4's tie-break is the lowest legal-action index. Hand order can therefore change a
policy's choice, so the reconstruction handles the two cases differently:

- The **observing seat's** current order is known, so it is preserved exactly: its
  own cards come first in the observed order and its played cards are appended.
  Removing the played cards during replay leaves the observed order intact, so the
  observer's own legal-action order - and its tie-break - is unchanged from the
  real deal.
- Every **other seat's** original order is not public and is not even meaningful to
  the observer, so it is canonicalized by deck index.

## A hypothetical can never be mistaken for a real deal

Three independent markers, and one structural impossibility.

| Marker | Value |
| --- | --- |
| `match_ref` | starts with `hypothetical:` (checked in `__post_init__`) |
| `is_hypothetical` | `True` |
| `visibility` | `research_private_hypothetical` |

The structural part matters more than the labels. Because opponent hand order is
canonicalized, a hypothetical's `deal_id` - a content digest over dealer and
ordered hands - **cannot** equal the real deal's, even when the sampled cards are
exactly right. `test_a_hypothetical_cannot_reproduce_the_real_deal_identity`
asserts that directly. A hypothetical filed as a dealt deal would be detectable by
its identity alone.

`provenance()` records the source `match_ref` and `deal_ref`, the phase, the trick
count, and an explicit `usage_rule`:

> A hypothetical continuation is search input only. It must never be recorded as a
> dealt deal, entered into a bank, or counted as an observation.

## What is verified after replay

`_require_same_decision_point` re-checks that the replay landed exactly where the
observation was: same phase, same acting seat, same completed-trick count, same
partial trick, same team trick totals, and the observing seat's own hand unchanged
in both content and order. A continuation that drifted by even one action would
raise rather than be solved.

## Cost

One continuation is one `create_deal_state` plus one `apply_action` per public
action, so it is linear in the deal's history - roughly 50 transitions late in a
deal. Each transition revalidates the whole state, which is why the engine catches
what it catches. For a determinizing search this is the dominant per-world cost
before the solver runs; a later phase that needs more throughput should measure
here first.
