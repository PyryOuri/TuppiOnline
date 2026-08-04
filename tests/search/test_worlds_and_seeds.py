"""The sampled-world set and the seed hierarchy."""

from __future__ import annotations

import pytest

from tuppi_exact import HardConstraintModel, feasible_assignment_count

from tuppi_search.config import PimcConfiguration
from tuppi_search.errors import SeedError, WorldSetError
from tuppi_search.random import (
    CANDIDATE_DEPENDENT_DOMAINS,
    SearchSeedHierarchy,
    SeedDomain,
    canonical_action_id,
    information_state_digest,
    stable_text_digest,
)
from tuppi_search.worlds import (
    MAXIMUM_ENUMERATION_COUNT,
    WorldSetMode,
    build_world_set,
    can_enumerate,
    world_identity,
)

from .conftest import walk_deal


def _seeds(observation, configuration, seed="fixed"):
    return SearchSeedHierarchy(
        pimc_protocol=configuration.pimc_protocol_version,
        information_state=information_state_digest(observation),
        decision_seed=seed,
    )


# ----------------------------------------------------------------- seeds


def test_world_sampling_must_not_depend_on_the_candidate_action(mid_position):
    """Passing a candidate to a candidate-independent domain is an error."""

    configuration = PimcConfiguration.build(world_count=2)
    seeds = _seeds(mid_position.observation, configuration)
    action_id = canonical_action_id(mid_position.observation.legal_actions[0])
    with pytest.raises(SeedError):
        seeds.derive(
            SeedDomain.HIDDEN_WORLD_SAMPLING, candidate_action_id=action_id
        )
    assert SeedDomain.HIDDEN_WORLD_SAMPLING not in CANDIDATE_DEPENDENT_DOMAINS
    # Rollout domains may legitimately depend on the action.
    assert seeds.derive(SeedDomain.ROLLOUT_REPLICA, candidate_action_id=action_id)


def test_domains_are_separated(mid_position):
    configuration = PimcConfiguration.build(world_count=2)
    seeds = _seeds(mid_position.observation, configuration)
    derived = {
        domain: seeds.derive(domain) for domain in SeedDomain
    }
    assert len(set(derived.values())) == len(SeedDomain)


def test_coordinates_change_the_seed(mid_position):
    configuration = PimcConfiguration.build(world_count=2)
    seeds = _seeds(mid_position.observation, configuration)
    base = seeds.derive(SeedDomain.ROLLOUT_SEAT_DECISION)
    variants = {
        base,
        seeds.derive(SeedDomain.ROLLOUT_SEAT_DECISION, sample_index=1),
        seeds.derive(SeedDomain.ROLLOUT_SEAT_DECISION, acting_seat=2),
        seeds.derive(SeedDomain.ROLLOUT_SEAT_DECISION, decision_index=3),
        seeds.derive(SeedDomain.ROLLOUT_SEAT_DECISION, rollout_replica=1),
    }
    assert len(variants) == 5


def test_the_seed_hierarchy_validates_its_inputs(mid_position):
    configuration = PimcConfiguration.build(world_count=2)
    seeds = _seeds(mid_position.observation, configuration)
    with pytest.raises(SeedError):
        SearchSeedHierarchy(
            pimc_protocol="", information_state="x", decision_seed="y"
        )
    with pytest.raises(SeedError):
        seeds.derive("not a domain")  # type: ignore[arg-type]
    with pytest.raises(SeedError):
        seeds.derive(SeedDomain.ANALYSIS, sample_index=-1)
    with pytest.raises(SeedError):
        seeds.derive(SeedDomain.ANALYSIS, acting_seat=7)


def test_stable_text_digest_does_not_use_python_hash():
    assert stable_text_digest("abc").startswith("sha256:")
    assert stable_text_digest("abc") == stable_text_digest("abc")
    with pytest.raises(SeedError):
        stable_text_digest(42)  # type: ignore[arg-type]


def test_the_information_state_digest_requires_an_observation():
    with pytest.raises(SeedError):
        information_state_digest("not an observation")  # type: ignore[arg-type]


# ------------------------------------------------------------------ worlds


def test_the_world_set_is_indexed_and_randomly_accessible(mid_position):
    configuration = PimcConfiguration.build(world_count=6)
    world_set = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=_seeds(mid_position.observation, configuration),
    )
    assert len(world_set) == 6
    assert world_set.requested_indices == (0, 1, 2, 3, 4, 5)
    for index in range(6):
        assert world_set.world(index).sample_index == index
    with pytest.raises(WorldSetError):
        world_set.world(6)
    with pytest.raises(WorldSetError):
        world_set.world(-1)


def test_prefixes_are_exact_and_nested(mid_position):
    configuration = PimcConfiguration.build(world_count=8)
    world_set = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=_seeds(mid_position.observation, configuration),
    )
    for count in (1, 2, 4, 8):
        prefix = world_set.prefix(count)
        assert len(prefix) == count
        assert [item.world_id for item in prefix.worlds] == [
            item.world_id for item in world_set.worlds[:count]
        ]
        assert prefix.feasible_assignment_count == (
            world_set.feasible_assignment_count
        )
    with pytest.raises(WorldSetError):
        world_set.prefix(9)


def test_a_smaller_budget_reproduces_the_larger_budget_prefix(mid_position):
    """Budgets nest, so an action-stability study is not confounded by re-rolling."""

    small = PimcConfiguration.build(world_count=2)
    large = PimcConfiguration.build(world_count=8)
    small_set = build_world_set(
        mid_position.observation,
        configuration=small,
        seeds=_seeds(mid_position.observation, small),
    )
    large_set = build_world_set(
        mid_position.observation,
        configuration=large,
        seeds=_seeds(mid_position.observation, large),
    )
    assert [item.world_id for item in small_set.worlds] == [
        item.world_id for item in large_set.worlds[:2]
    ]


def test_duplicates_are_counted_and_never_removed(late_position):
    """Late in a deal the feasible set can be tiny, so repeats must be kept."""

    configuration = PimcConfiguration.build(world_count=16)
    world_set = build_world_set(
        late_position.observation,
        configuration=configuration,
        seeds=_seeds(late_position.observation, configuration),
    )
    assert len(world_set) == 16
    assert world_set.unique_world_count + world_set.duplicate_count == 16
    assert 0.0 <= world_set.duplicate_fraction <= 1.0
    data = world_set.to_data()
    assert data["duplicate_count"] == world_set.duplicate_count
    assert data["requested_world_count"] == 16


def test_the_exact_feasible_count_is_reported(mid_position):
    configuration = PimcConfiguration.build(world_count=2)
    model = HardConstraintModel.build(mid_position.observation)
    expected = feasible_assignment_count(model)
    world_set = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=_seeds(mid_position.observation, configuration),
    )
    assert world_set.feasible_assignment_count == expected
    assert world_set.unknown_card_count == len(model.unknown_cards)


def test_every_world_satisfies_the_hard_constraints(mid_position):
    configuration = PimcConfiguration.build(world_count=6)
    model = HardConstraintModel.build(mid_position.observation)
    world_set = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=_seeds(mid_position.observation, configuration),
    )
    for world in world_set.worlds:
        state = world.state
        # The engine validated the whole replay, so legality is already assured;
        # the extra check is that the *observer's* hand is untouched.
        assert tuple(state.hands[model.observing_seat]) == tuple(
            mid_position.observation.own_hand
        )
        for seat in range(4):
            for card in model.known_held[seat]:
                if card in state.hands[seat]:
                    continue
                raise AssertionError("a publicly known card moved seats")


def test_the_world_identity_excludes_the_observers_own_hand(mid_position):
    """A world identity must not encode a real hand."""

    from tuppi_exact import UniformFeasibleSampler
    from tuppi_rules import card_to_code

    configuration = PimcConfiguration.build(world_count=2)
    model = HardConstraintModel.build(mid_position.observation)
    sampler = UniformFeasibleSampler.build(model, seed="identity")
    assignment = sampler.sample_one()
    identity = world_identity(assignment)
    assert identity.startswith("world:sha256:")
    for card in mid_position.observation.own_hand:
        assert card_to_code(card) not in identity


def test_exact_enumeration_is_labelled_and_complete(late_position):
    """An enumerated set answers a different question and must say so."""

    if not can_enumerate(late_position.observation):
        pytest.skip("this position's feasible set is too large to enumerate")
    model = HardConstraintModel.build(late_position.observation)
    total = feasible_assignment_count(model)
    configuration = PimcConfiguration.build(world_count=max(total, 1))
    world_set = build_world_set(
        late_position.observation,
        configuration=configuration,
        seeds=_seeds(late_position.observation, configuration),
        mode=WorldSetMode.EXACT_ENUMERATION,
    )
    assert world_set.mode is WorldSetMode.EXACT_ENUMERATION
    assert world_set.to_data()["mode"] == "exact_enumeration"
    assert len(world_set) == total
    assert world_set.duplicate_count == 0
    assert world_set.unique_world_count == total


def test_enumeration_refuses_an_impractically_large_feasible_set(mid_position):
    model = HardConstraintModel.build(mid_position.observation)
    if feasible_assignment_count(model) <= MAXIMUM_ENUMERATION_COUNT:
        pytest.skip("this position is small enough to enumerate")
    configuration = PimcConfiguration.build(world_count=2)
    with pytest.raises(WorldSetError):
        build_world_set(
            mid_position.observation,
            configuration=configuration,
            seeds=_seeds(mid_position.observation, configuration),
            mode=WorldSetMode.EXACT_ENUMERATION,
        )


def test_a_fully_determined_position_reports_itself_as_such():
    configuration = PimcConfiguration.build(world_count=2)
    for position in walk_deal(stream_index=1):
        model = HardConstraintModel.build(position.observation)
        if model.unknown_cards:
            continue
        world_set = build_world_set(
            position.observation,
            configuration=configuration,
            seeds=_seeds(position.observation, configuration),
        )
        assert world_set.fully_determined is True
        assert world_set.feasible_assignment_count == 1
        assert world_set.unique_world_count == 1
        return
    pytest.skip("no fully determined position was reached")


def test_the_world_set_id_is_stable_and_content_addressed(mid_position):
    configuration = PimcConfiguration.build(world_count=4)
    first = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=_seeds(mid_position.observation, configuration),
    )
    again = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=_seeds(mid_position.observation, configuration),
    )
    assert first.world_set_id == again.world_set_id
    other = build_world_set(
        mid_position.observation,
        configuration=configuration,
        seeds=_seeds(mid_position.observation, configuration, seed="different"),
    )
    assert other.world_set_id != first.world_set_id


def test_malformed_world_set_requests_are_refused(mid_position):
    configuration = PimcConfiguration.build(world_count=2)
    seeds = _seeds(mid_position.observation, configuration)
    with pytest.raises(WorldSetError):
        build_world_set("not an observation", configuration=configuration, seeds=seeds)
    with pytest.raises(WorldSetError):
        build_world_set(
            mid_position.observation, configuration="not a config", seeds=seeds
        )
    with pytest.raises(WorldSetError):
        build_world_set(
            mid_position.observation, configuration=configuration, seeds="not seeds"
        )
    with pytest.raises(WorldSetError):
        world_identity("not an assignment")  # type: ignore[arg-type]
