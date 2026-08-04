# The exact tail, and why it may make PIMC worse

When the exact tail is enabled and a rollout reaches a trick-play position with at
most `exact_tail_max_tricks_remaining` tricks left, the rollout stops and the
Phase 5B solver supplies the position's exact double-dummy value instead.

## Compatible utility, by construction

The solver's answer and a completed rollout both reduce to the *same* value type -
`DealOutcomeSummary`, carrying `(contract, declarer, team0 tricks, starting score,
root team)` - and both are scored by the same adapter.

"The exact solver and the rollout use compatible utility semantics" is therefore not
a property maintained by hand and checked for drift. There is one scoring function
and one input type, so the two paths *cannot* disagree. `tests/search/test_utilities.py`
asserts the type identity and the equal scoring; `tests/search/test_exact_tail.py`
adds the empirical version at one trick remaining, where every card is forced and the
two continuations genuinely coincide.

## The tail is not variance reduction

This is the part that is easy to get wrong, so it is stated plainly.

The tail does **not** compute the same quantity more precisely. It computes a
different quantity:

| | Continuation from the threshold onwards |
| --- | --- |
| tail off | the configured Phase 4 reference policy, observation-only |
| tail on | optimal play by all four seats, each seeing every card |

So turning it on changes the estimand:

- **off:** "this action, then reference play by everyone";
- **on:** "this action, then reference play until the endgame, then perfect play by
  four clairvoyant players".

## Why that direction is suspicious

Phase 5C's rollout is deliberately observation-only, which removes the sharpest form
of PIMC's continuation clairvoyance: each simulated seat sees only what it would
really see. The exact tail **puts that clairvoyance back**, in the part of the deal
where card knowledge matters most.

Every seat in the tail knows every card. A defender who could not possibly locate a
key card finds it; a declarer who would have guessed wrong guesses right. The
resulting value is exact *about the sampled world* and systematically detached from
what any real player could achieve. That is textbook perfect-information bias, and
concentrating it in the endgame is not obviously an improvement.

Phase 5C therefore **measures** the tail rather than assuming it helps, and the
documentation says so before any result is quoted. `tests/search/test_exact_tail.py`
contains a test named `test_tail_and_no_tail_may_disagree_and_that_is_expected`,
which asserts legality and determinism and explicitly does *not* assert agreement.

## The threshold

Explicit configuration, behaviourally material, and part of the agent identity. It is
chosen from the **Phase 5B solver benchmark**, not carried over from another card
game:

| Tricks remaining | Mean solve | Worst case |
| ---: | ---: | ---: |
| 3 | 0.18 ms | 0.6 ms |
| 4 | **0.86 ms** | 4.4 ms |
| 5 | 5.6 ms | 30 ms |

At tens of solver calls per PIMC decision, a threshold of 5 costs roughly 6.5x what
4 does to buy one more exact trick. The registered
`uniform_feasible_pimc_exact_tail_v1` therefore uses **4**, and the configuration
refuses anything above 5 - the largest depth Phase 5B measured as exact.

Changing the threshold changes the `configuration_id` and therefore the `agent_id`;
`tests/search/test_exact_tail.py` asserts that thresholds 2, 3, 4 and "off" are four
distinct identities.

## Cost, which cuts the other way

The tail also makes decisions *cheaper*, because it truncates the most expensive part
of every rollout. Measured median decision latency:

| Worlds | Tail off | Tail on (threshold 4) |
| ---: | ---: | ---: |
| 2 | 624 ms | 354 ms |
| 4 | 1 265 ms | 699 ms |
| 8 | 2 494 ms | 1 403 ms |

So the tail is roughly a 1.8x speedup. That is a genuine practical advantage and it
is *not* an argument that it plays better.

## Failure policy

The solver can refuse - a node budget exceeded, a position out of range. Two
configured behaviours, both explicit:

- `strict` (the registered default): raise `ExactTailError` and invalidate the
  decision. No silent partial exact result.
- `fallback_rollout`: record the refusal, count the solver call, and continue with the
  rollout.

There is no third option in which a refusal is ignored, and the failure policy is part
of the agent identity.

## Where the solver output may not go

Nowhere public. The tail runs inside a hypothetical world; its value reaches only the
candidate aggregation. `tests/search/test_exact_tail.py` asserts that a tail decision
leaves the acting seat's observation byte-identical, and
`tests/search/test_architecture.py` asserts that `tuppi_engine.serialization` contains
no reference to any search object and that the public event log is unchanged by a
decision.
