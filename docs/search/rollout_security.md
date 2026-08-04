# The rollout boundary

The rollout is where Phase 5C could most easily cheat, so it is built so that
cheating is not expressible.

## The loop, in full

At every simulated decision inside a hypothetical world:

1. project the hypothetical `DealState` to the acting seat's `PlayerObservation`
   using the engine's own `observation_for`;
2. hand **only that observation** to the rollout policy;
3. check that the returned action belongs to the acting seat and is in the legal set
   the engine offered;
4. apply it through `apply_action`, which revalidates the entire deal state.

The policy is never passed the state. There is no argument for it.

## How that is verified

Not by reading the code. `tests/search/test_rollout_security.py` wraps every
rollout policy in a recorder and asserts, for **every call made during real
rollouts**, that:

- exactly one positional argument was passed and no keyword arguments;
- that argument was a `PlayerObservation`;
- its `observing_seat` and `current_actor` were the acting seat.

A second test asserts that no argument was ever a `DealState` or `MatchState`, and a
third inspects `UniformFeasiblePimcAgent.__init__` and `choose_action` to confirm
the deployable agent has no parameter through which a full state could arrive:

```text
__init__      -> {self, agent_id, configuration, seat, policy_seed}
choose_action -> {self, observation}
```

## Illegal actions are never repaired

If a rollout policy returns an action the engine rejects, Phase 5C raises
`IllegalRolloutActionError` and the whole decision is invalidated. It does **not**
substitute a legal action.

The frozen legacy emulator did substitute, and Phase 0B recorded it as a fidelity
failure. Repairing an illegal action would hide a defect and silently change the
estimator: the value being averaged would no longer be the value of the policy under
test.

Three separate refusals exist, because they catch different mistakes:

| Condition | Meaning |
| --- | --- |
| action's seat is not the acting seat | the policy is confused about who it is |
| action is not in the offered legal set | the policy is proposing something the rules forbid |
| the engine rejects the transition | the world or the action is unsound |

## Distinct agents per seat, fresh per rollout

Each seat gets its own distinct agent object, so no state can couple two simulated
partners - which is exactly the coupling a partnership convention must not get for
free.

Agents are constructed fresh for each rollout rather than reused. Phase 4 policies
are stateless, so reuse would be safe today; constructing fresh costs about 0.2 % of
a rollout and removes the need to depend on that remaining true.

## The search agent's own boundary

The deployable agent receives:

- a formal `PlayerObservation`;
- an immutable `PimcConfiguration`;
- an explicit policy seed;
- its seat index.

It does not receive, and has nowhere to receive: the true engine state, the true
hidden hands, the explicit real deal, a hidden-state-derived deal identifier, an
evaluator fixture identity, a research result, sealed-bank metadata, server-private
state, a full-state cache, or true future actions.

`require_no_full_state` is available as defence in depth at the entry points, but
the real protection is that there is nowhere to put one.

## Why `apply_action` is used despite the cost

`apply_action` revalidates the whole deal state on every transition, so a rollout is
O(remaining actions x history length) - about 86 ms from a showing root. That
validation is the reason an unsound sampled world, an illegal policy action, or a
mis-replayed history surfaces as an exception rather than as a plausible-looking
number.

The cost is reported rather than optimized away. It is the single largest factor in
Phase 5C's budgets, and accepting it is what lets the phase claim that every rollout
was a legal `project_target_v1` deal.
