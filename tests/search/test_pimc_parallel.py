"""Within-decision parallelism, which must be invisible in the result.

Gate zero measured W=64 at a cold maximum of 8.08 s against an 8 s admission
margin, and C3 measured the deal-points effect clearing delta only at W=64. The
two gates did not overlap, and the only route that did not involve weakening one
of them was to make a single decision faster. `pimc.decide(workers=N)` evaluates
the candidates concurrently.

The entire correctness argument is that nothing observable changes:

* every candidate is evaluated against the same world set, rebuilt
  deterministically from the same seeds in each worker;
* `_evaluate_candidate` is a pure function of its arguments, so a candidate's
  summary does not depend on what else is running;
* results are reassembled by `action_order_index` before the tie-break sees
  them, so completion order cannot reach the selection.

So these tests require identity, not similarity — the same diagnostics, the same
`configuration_id`, the same `agent_id`.
"""

from __future__ import annotations

import pytest

from tuppi_search import pimc
from tuppi_search.config import PimcConfiguration
from tuppi_search.diagnostics import PimcDecisionDiagnostics
from tuppi_search.errors import PimcDecisionError
from tuppi_search.hybrid import construct_gated_agent
from tuppi_search.registry import (
    build_agent,
    opening_lead_gate,
    opening_lead_specification,
    specification_for,
)
from tuppi_search.rollout import SeatPolicies

#: Small enough to keep the suite quick; the property is independent of budget.
WORLDS = 2
SEED = "tuppi-parallel-differential-v1"


def _diagnostics(decision, seat):
    policies = SeatPolicies(configuration=decision.configuration, root_seat=seat)
    return PimcDecisionDiagnostics(
        agent_id="agent:sha256:" + "0" * 8,
        decision=decision,
        rollout_policy_agent_ids=policies.policy_agent_ids,
    ).to_data()


def _decide(observation, configuration, workers):
    return pimc.decide(
        observation,
        configuration=configuration,
        decision_seed=SEED,
        workers=workers,
    )


@pytest.mark.parametrize("workers", [2, 3])
def test_the_decision_is_identical_however_many_workers_run_it(
    mid_position, workers
):
    configuration = PimcConfiguration.build(world_count=WORLDS)
    seat = mid_position.observation.observing_seat
    serial = _decide(mid_position.observation, configuration, 1)
    parallel = _decide(mid_position.observation, configuration, workers)
    assert _diagnostics(serial, seat) == _diagnostics(parallel, seat)


def test_the_opening_lead_is_identical_in_parallel():
    """The decision the parallelism exists for: 13 independent candidates."""

    from .conftest import advance_to

    position = advance_to(tricks=0)
    assert position.legal_action_count == 13
    configuration = PimcConfiguration.build(
        world_count=WORLDS, showing_search_enabled=False
    )
    seat = position.observation.observing_seat
    serial = _decide(position.observation, configuration, 1)
    parallel = _decide(position.observation, configuration, 4)
    assert _diagnostics(serial, seat) == _diagnostics(parallel, seat)
    assert serial.selected_action == parallel.selected_action


def test_more_workers_than_candidates_is_harmless(mid_position):
    configuration = PimcConfiguration.build(world_count=WORLDS)
    seat = mid_position.observation.observing_seat
    serial = _decide(mid_position.observation, configuration, 1)
    flooded = _decide(mid_position.observation, configuration, 64)
    assert _diagnostics(serial, seat) == _diagnostics(flooded, seat)


def test_the_incumbent_continuation_is_identical_in_parallel(mid_position):
    """Parallelism must hold for a continuation it was never measured against."""

    configuration = PimcConfiguration.build(
        world_count=WORLDS, rollout_policy_key="partner_aware_lead_v2"
    )
    seat = mid_position.observation.observing_seat
    serial = _decide(mid_position.observation, configuration, 1)
    parallel = _decide(mid_position.observation, configuration, 3)
    assert _diagnostics(serial, seat) == _diagnostics(parallel, seat)


def test_an_exact_tail_is_identical_in_parallel(late_position, tail_config):
    """The tail is rebuilt per worker, so its verdicts must still agree."""

    seat = late_position.observation.observing_seat
    serial = _decide(late_position.observation, tail_config, 1)
    parallel = _decide(late_position.observation, tail_config, 3)
    assert _diagnostics(serial, seat) == _diagnostics(parallel, seat)


def test_worker_count_is_not_part_of_the_configuration_identity(mid_position):
    """`config`'s docstring puts worker count among the things that cannot
    change what the agent plays. This holds it to that."""

    configuration = PimcConfiguration.build(world_count=WORLDS)
    serial = _decide(mid_position.observation, configuration, 1)
    parallel = _decide(mid_position.observation, configuration, 3)
    assert serial.configuration.configuration_id == (
        parallel.configuration.configuration_id
    )
    assert serial.configuration == parallel.configuration


def test_worker_count_is_not_part_of_the_agent_identity(mid_position):
    key = "uniform_feasible_pimc_smoke_v1"
    seat = mid_position.observation.observing_seat
    serial = build_agent(key, seat=seat)
    assert serial.workers == 1
    parallel = type(serial)(
        agent_id=specification_for(key).agent_id,
        configuration=serial.configuration,
        seat=seat,
        workers=4,
    )
    assert parallel.workers == 4
    assert parallel.identity == serial.identity
    assert parallel.choose_action(mid_position.observation) == (
        serial.choose_action(mid_position.observation)
    )


def test_the_scoped_selector_can_parallelise_the_one_decision_it_searches(
    mid_position,
):
    """An opening-lead gate searches once per deal, so workers buy latency on
    exactly the decision under the bound."""

    pimc_configuration = PimcConfiguration.build(
        world_count=WORLDS, showing_search_enabled=False
    )
    gate = opening_lead_gate(pimc=pimc_configuration)
    specification = opening_lead_specification(pimc=pimc_configuration)
    seat = mid_position.observation.observing_seat
    serial = construct_gated_agent(specification, seat=seat, gate=gate)
    parallel = construct_gated_agent(
        specification, seat=seat, gate=gate, workers=4
    )
    assert serial.workers == 1
    assert parallel.workers == 4
    # Same identity: the specification does not record the worker count.
    assert serial.identity == parallel.identity
    # And a delegated decision is unaffected either way.
    assert parallel.choose_action(mid_position.observation) == (
        serial.choose_action(mid_position.observation)
    )


@pytest.mark.parametrize("bad", [0, -1, 1.5, "4", None, True])
def test_a_nonsensical_worker_count_is_refused(mid_position, bad):
    configuration = PimcConfiguration.build(world_count=WORLDS)
    with pytest.raises(PimcDecisionError, match="workers must be an integer"):
        pimc.decide(
            mid_position.observation,
            configuration=configuration,
            decision_seed=SEED,
            workers=bad,
        )


def test_a_forced_action_needs_no_workers(forced_position):
    """The single-legal-action shortcut returns before any pool is created."""

    configuration = PimcConfiguration.build(world_count=WORLDS)
    decision = _decide(forced_position.observation, configuration, 8)
    assert decision.single_legal_action_shortcut
    assert decision.world_set is None


def test_a_reused_world_set_stays_serial(mid_position):
    """The action-stability study passes its own world set, which the parallel
    path cannot accept, so it must fall back rather than silently ignore it."""

    configuration = PimcConfiguration.build(world_count=WORLDS)
    first = _decide(mid_position.observation, configuration, 1)
    assert first.world_set is not None
    reused = pimc.decide(
        mid_position.observation,
        configuration=configuration,
        decision_seed=SEED,
        reuse_world_set=first.world_set,
        workers=8,
    )
    seat = mid_position.observation.observing_seat
    assert _diagnostics(first, seat) == _diagnostics(reused, seat)
