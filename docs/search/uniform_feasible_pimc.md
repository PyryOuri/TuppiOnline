# Uniform-feasible PIMC, and strategy fusion

## The algorithm

For one root observation, in order:

1. **Enumerate legal root actions** in the engine's canonical order. At a showing
   root these are `(declared contract, shown card)` pairs; during trick play they
   are card plays.
2. **Build the hard constraint set** with Phase 5B's `HardConstraintModel`,
   including the show-derived exclusions that a public verbal fallback proves.
3. **Sample one indexed world set**, uniformly over the hard-feasible assignments,
   from a seed that depends on the information state and the decision seed - and
   **not** on any candidate action.
4. **Construct one hypothetical world per sample** by replaying the public history
   through the real engine, so an unsound world raises instead of being searched.
5. **For every candidate, in every world:** apply the candidate, then complete the
   deal with observation-only rollout policies (optionally handing the endgame to
   the exact solver).
6. **Score each completed deal for the root team** through one versioned utility
   adapter.
7. **Average per candidate**, select the highest mean, break exact ties by the
   lowest canonical legal-action index.

## The common world set is the load-bearing property

Every candidate is evaluated on the *same* indexed worlds. This is common random
numbers, and without it the comparison between two actions would be a comparison
between two independent noisy samples: at four worlds, sampling noise would swamp
any real difference between candidates.

It is enforced structurally rather than by convention. `build_world_set` has no
parameter through which a candidate could enter, the world-set identity contains no
action, and `tests/search/test_pimc_core.py` inspects the signature and the
serialized identity to confirm both.

## One ply, deliberately

After the forced root action, **every** seat - including the root seat's own later
turns - plays the configured rollout policy. The PIMC agent is never invoked
recursively inside its own rollout.

That makes the estimated quantity precise and modest: *"the value of this action if
everyone, including me, plays the reference policy afterwards"*. It is not the value
of the action under continued search. A `root_continuation` mode exists for using a
different policy at the root seat's later turns, but it is a distinct configuration
with a distinct agent identity, and it is not the default.

## Duplicates are kept

Independent uniform draws over a finite feasible set produce repeats, and late in a
deal the feasible set is sometimes a single world. Duplicates are counted and
reported, never removed: deduplicating would silently convert a uniform average over
*draws* into a uniform average over *distinct worlds*, which is a different
estimator.

## Strategy fusion

This is the structural limitation of PIMC, and it must not be papered over. It is why
uniform-feasible PIMC is a baseline and not an equilibrium solver, and why no result
from it may be described as optimal imperfect-information play.

PIMC samples a complete hidden world, lets the continuation play *that* world out,
and averages the values afterwards. The action it selects therefore maximizes

```text
mean over worlds w of  value( action, continuation adapted to w )
```

but a real player must commit to **one** strategy that works across all worlds
consistent with what it knows. Those are different objects. PIMC can pick an action
whose value comes from combining world-specific continuations that no single
strategy could implement simultaneously - it *fuses* mutually incompatible plans.

Three consequences follow, and all three are load-bearing:

- **PIMC values are not information-set-optimal.** They are not lower bounds either;
  they can be optimistic or pessimistic depending on the position.
- **More samples do not fix it.** Additional worlds shrink Monte Carlo error around
  the fused value. The fused value is the wrong target, and averaging more of it
  converges to the wrong number more precisely. Phase 5C measured exactly that: the
  RAMI declaration rate moved *further* from the reference agent's as the world
  count rose from 2 to 16.
- **The exact tail makes it worse, not better.** See
  `docs/search/exact_tail_integration.md`.

Phase 5C mitigates one part of the classical problem and not the other. Because the
rollout is **observation-only**, the continuation does *not* react to the sampled
world - each simulated seat sees only its own hand and the public record, exactly as
in a real deal. That removes the sharpest form of continuation clairvoyance. What
remains is fusion at the **root**: the averaging step still combines worlds, and the
root action is still chosen as if the agent could tailor its choice per world.

## The second bias: policy mismatch

There is a further mismatch that is specific to using PIMC in a partnership game,
and it is probably the larger effect in Phase 5C's own results.

PIMC estimates the value of an action assuming **reference play by all four seats**
afterwards, including its own partner. In a real match, both of the candidate
partnership's seats play PIMC. So the estimate mis-models the continuation of its
own side. If PIMC's play is *worse* than the reference policy - which Phase 5C's
complete-match comparison found it to be - then every value it computes is
optimistic about its own partnership, and the error is self-referential rather than
random.

Nothing in Phase 5C corrects this. Recognizing it is the point: it is a reason to
expect a one-ply PIMC baseline built on a reference rollout to *underperform* that
reference, which is what happened.

## What PIMC must never be called

Not "solving uncertainty". Not "optimal against unknown hands". Not "an
approximation that improves with more samples" without saying which error it
improves. It is a baseline whose bias is named, bounded in direction where possible,
and measured.

## Cost

A decision costs roughly `legal_actions x world_count x rollout`. Measured on this
machine: a rollout is about 6.8 ms per remaining trick (86 ms from a showing root),
mean legal actions are 3.76 in trick play and 6.71 at showing, and 24 % of
trick-play decisions are forced and cost nothing. Median decision latency is 624 ms
at two worlds and 2 494 ms at eight. Full figures and their consequences for the
evaluation design are in `docs/search/phase5c_evaluation.md`.
