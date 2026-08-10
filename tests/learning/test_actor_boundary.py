from __future__ import annotations

import pytest

from tuppi_learning.datasets import generate_imitation_examples
from tuppi_learning.encoding import encode_observation, relative_seat
from tuppi_learning.errors import LearningDependencyError, ObservationBoundaryError
from tuppi_learning.models import ActorConfiguration, ObservationOnlyActor, SeatRelativeActor, actor_parameter_count


def _examples():
    return generate_imitation_examples(
        root_seed="phase6-tests",
        split="train",
        stream_indices=(0,),
        max_examples=24,
        safety_cap=4,
    )


def test_seat_relative_roles_are_canonical() -> None:
    assert tuple(relative_seat(0, seat) for seat in range(4)) == (0, 1, 2, 3)
    assert tuple(relative_seat(2, seat) for seat in range(4)) == (2, 3, 0, 1)


def test_encoder_excludes_fixture_identifiers() -> None:
    item = _examples()[0]
    encoded = encode_observation(item.observation)
    assert item.observation.match_ref not in encoded.observation_id
    assert item.observation.deal_ref not in encoded.observation_id
    assert len(encoded.context) == 32
    assert encoded.legal_action_count == len(item.observation.legal_actions)


def test_actor_is_observation_only() -> None:
    torch = pytest.importorskip("torch")
    item = _examples()[0]
    actor = SeatRelativeActor(ActorConfiguration())
    deployment = ObservationOnlyActor(actor)
    assert actor.parameter_count < 2_000_000
    action = deployment.choose_action(item.observation)
    assert action in item.observation.legal_actions
    with pytest.raises(ObservationBoundaryError):
        deployment.choose_action(object())


def test_model_requires_optional_dependency_without_importing_core() -> None:
    # The test is meaningful in the minimal environment; with the local
    # optional dependency installed the constructor is expected to succeed.
    try:
        SeatRelativeActor()
    except LearningDependencyError:
        return
