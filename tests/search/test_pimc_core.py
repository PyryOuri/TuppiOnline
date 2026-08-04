"""The PIMC contract: common worlds, one forced action, deterministic selection."""

from __future__ import annotations

import pytest

from tuppi_engine import EnginePhase, PlayCardAction, ShowAction
from tuppi_rules import TRICKS_PER_DEAL, team_for_seat

from tuppi_search.config import PimcConfiguration, RootContinuation
from tuppi_search.errors import PimcDecisionError
from tuppi_search.pimc import decide
from tuppi_search.random import canonical_action_id
from tuppi_search.worlds import build_world_set
from tuppi_search.random import SearchSeedHierarchy, information_state_digest

from .conftest import advance_to, walk_deal


def _seeds(observation, configuration, seed="fixed"):
    return SearchSeedHierarchy(
        pimc_protocol=configuration.pimc_protocol_version,
        information_state=information_state_digest(observation),
        decision_seed=seed,
    )


def test_every_legal_action_is_evaluated_and_no_other(mid_position, smoke_config):
    decision = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    legal = mid_position.observation.legal_actions
    assert len(decision.candidates) == len(legal)
    assert tuple(item.action for item in decision.candidates) == tuple(legal)
    assert tuple(item.action_order_index for item in decision.candidates) == tuple(
        range(len(legal))
    )
    assert decision.selected_action in legal


def test_every_candidate_uses_the_same_world_set(mid_position, smoke_config):
    """The load-bearing property: one world set, shared by all candidates."""

    decision = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    assert decision.world_set is not None
    expected = len(decision.world_set) * smoke_config.rollout_replicas
    for candidate in decision.candidates:
        assert candidate.evaluations == expected
        assert candidate.unique_worlds == decision.world_set.unique_world_count


def test_the_world_set_cannot_depend_on_the_candidate(mid_position, smoke_config):
    """``build_world_set`` has no candidate parameter, and its identity has none."""

    import inspect

    signature = inspect.signature(build_world_set)
    assert "action" not in signature.parameters
    assert "candidate" not in signature.parameters
    seeds = _seeds(mid_position.observation, smoke_config)
    world_set = build_world_set(
        mid_position.observation, configuration=smoke_config, seeds=seeds
    )
    identity = world_set.identity_data()
    serialized = repr(identity)
    for candidate in mid_position.observation.legal_actions:
        assert canonical_action_id(candidate) not in serialized


def test_the_forced_root_action_is_applied_exactly_once(mid_position, smoke_config):
    """Each rollout starts with one applied action and completes the deal."""

    decision = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    remaining_actions = (
        TRICKS_PER_DEAL * 4
        - sum(len(trick.plays) for trick in mid_position.observation.completed_tricks)
        - len(mid_position.observation.current_trick)
    )
    for candidate in decision.candidates:
        per_rollout = candidate.actions_simulated / candidate.evaluations
        assert per_rollout == remaining_actions


def test_all_rollouts_complete_the_deal(mid_position, smoke_config):
    decision = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    for candidate in decision.candidates:
        assert candidate.failures == 0
        assert candidate.evaluations > 0
        assert -1.0 <= candidate.minimum <= candidate.maximum <= 1.0


def test_selection_is_the_deterministic_tie_broken_maximum(mid_position, smoke_config):
    decision = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    best = max(item.mean_utility for item in decision.candidates)
    tied = [
        item for item in decision.candidates if item.mean_utility == best
    ]
    assert decision.selected_value == best
    assert decision.selected_index == min(item.action_order_index for item in tied)
    assert decision.selection_gap >= 0.0


def test_the_same_input_and_seed_produce_the_same_action(mid_position, smoke_config):
    first = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    again = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    assert first.selected_action == again.selected_action
    assert [item.mean_utility for item in first.candidates] == [
        item.mean_utility for item in again.candidates
    ]
    assert first.world_set.world_set_id == again.world_set.world_set_id


def test_a_different_seed_may_change_the_worlds_but_not_the_legality(
    mid_position, smoke_config
):
    first = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    other = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="b"
    )
    assert first.world_set.world_sampling_seed != other.world_set.world_sampling_seed
    assert other.selected_action in mid_position.observation.legal_actions


def test_the_single_action_shortcut_cannot_change_the_action(
    forced_position, smoke_config
):
    with_shortcut = decide(
        forced_position.observation,
        configuration=smoke_config,
        decision_seed="a",
    )
    without = decide(
        forced_position.observation,
        configuration=smoke_config,
        decision_seed="a",
        use_single_action_shortcut=False,
    )
    assert with_shortcut.single_legal_action_shortcut is True
    assert without.single_legal_action_shortcut is False
    assert with_shortcut.selected_action == without.selected_action
    assert with_shortcut.world_set is None
    assert without.world_set is not None


def test_root_team_orientation_is_correct_for_every_seat(
    positions_by_seat, smoke_config
):
    for seat, position in sorted(positions_by_seat.items()):
        decision = decide(
            position.observation, configuration=smoke_config, decision_seed="orient"
        )
        assert decision.root_seat == seat
        assert decision.root_team is team_for_seat(seat)
        # Deal wins counted for the root team can never exceed the evaluations.
        for candidate in decision.candidates:
            assert 0 <= candidate.root_team_deal_wins <= candidate.evaluations


def test_future_root_turns_use_the_rollout_policy_not_recursive_search(
    mid_position, smoke_config, monkeypatch
):
    """PIMC must never be invoked inside its own rollout."""

    import tuppi_search.pimc as pimc_module

    calls = {"count": 0}
    original = pimc_module.decide

    def counting_decide(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] > 1:
            raise AssertionError("PIMC was invoked recursively during its rollout")
        return original(*args, **kwargs)

    monkeypatch.setattr(pimc_module, "decide", counting_decide)
    pimc_module.decide(
        mid_position.observation, configuration=smoke_config, decision_seed="a"
    )
    assert calls["count"] == 1
    assert smoke_config.root_continuation is RootContinuation.ROLLOUT_POLICY


def test_a_nonacting_observation_is_refused(mid_position, smoke_config):
    from tuppi_engine import observation_for

    actor = mid_position.deal_state.current_actor
    other = (actor + 1) % 4
    observation = observation_for(mid_position.deal_state, other)
    with pytest.raises(PimcDecisionError):
        decide(observation, configuration=smoke_config, decision_seed="a")


def test_malformed_requests_are_refused(mid_position, smoke_config):
    with pytest.raises(PimcDecisionError):
        decide("not an observation", configuration=smoke_config, decision_seed="a")
    with pytest.raises(PimcDecisionError):
        decide(mid_position.observation, configuration=smoke_config, decision_seed="")
    with pytest.raises(PimcDecisionError):
        decide(
            mid_position.observation, configuration="not a config", decision_seed="a"
        )


def test_a_reused_world_set_must_match_the_information_state(
    mid_position, smoke_config
):
    other = advance_to(tricks=6)
    seeds = _seeds(other.observation, smoke_config)
    foreign = build_world_set(
        other.observation, configuration=smoke_config, seeds=seeds
    )
    with pytest.raises(PimcDecisionError):
        decide(
            mid_position.observation,
            configuration=smoke_config,
            decision_seed="a",
            reuse_world_set=foreign,
        )


def test_aggregation_is_invariant_to_evaluation_order(mid_position, smoke_config):
    """Every reported statistic is a function of the multiset of utilities."""

    from tuppi_search.pimc import WorldEvaluation, _aggregate

    evaluations = tuple(
        WorldEvaluation(
            sample_index=index,
            replica=0,
            utility=value,
            exact_tail_used=False,
            actions_simulated=10,
            solver_calls=0,
            solver_nodes=0,
            root_team_wins_deal=value > 0,
            match_terminal=False,
        )
        for index, value in enumerate((0.25, -0.5, 0.75, 0.0))
    )
    action = mid_position.observation.legal_actions[0]
    forward = _aggregate(
        action=action,
        action_order_index=0,
        evaluations=evaluations,
        unique_worlds=4,
    )
    backward = _aggregate(
        action=action,
        action_order_index=0,
        evaluations=tuple(reversed(evaluations)),
        unique_worlds=4,
    )
    assert forward.to_data() == backward.to_data()


def test_no_module_global_random_state_is_used():
    """A search that touched the global RNG would not be reproducible."""

    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "tuppi_search"
    for module in sorted(root.glob("*.py")):
        text = module.read_text(encoding="utf-8")
        assert "import random" not in text, module
        assert "random.random" not in text, module
        assert "random.shuffle" not in text, module
        assert "numpy.random" not in text, module


def test_showing_and_trick_play_are_both_supported(
    showing_position, mid_position, smoke_config
):
    show = decide(
        showing_position.observation, configuration=smoke_config, decision_seed="s"
    )
    play = decide(
        mid_position.observation, configuration=smoke_config, decision_seed="p"
    )
    assert show.phase == EnginePhase.SHOWING.value
    assert isinstance(show.selected_action, ShowAction)
    assert play.phase == EnginePhase.TRICK_PLAY.value
    assert isinstance(play.selected_action, PlayCardAction)


def test_a_configuration_without_showing_search_refuses_a_showing_root(
    showing_position,
):
    configuration = PimcConfiguration.build(
        world_count=2, showing_search_enabled=False
    )
    with pytest.raises(PimcDecisionError):
        decide(
            showing_position.observation,
            configuration=configuration,
            decision_seed="s",
        )


def test_every_visited_position_of_a_deal_is_decidable(smoke_config):
    """A smoke pass over one whole deal: PIMC must never fail mid-deal."""

    decided = 0
    for position in walk_deal(stream_index=1):
        if position.legal_action_count < 2:
            continue
        decision = decide(
            position.observation,
            configuration=smoke_config,
            decision_seed=f"walk-{decided}",
        )
        assert decision.selected_action in position.observation.legal_actions
        decided += 1
        if decided >= 4:
            break
    assert decided >= 4
