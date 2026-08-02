from __future__ import annotations

import pytest

from tuppi_match import MatchStream, stream_family
from tuppi_match.errors import StreamError
from tuppi_match.streams import MAXIMUM_DEAL_INDEX, STREAM_PROTOCOL_VERSION
from tuppi_rules import FULL_DECK, rotate_dealer, validate_initial_hands


def stream(index: int = 0, dealer: int = 0, seed: str = "test-stream") -> MatchStream:
    return MatchStream.build(root_seed=seed, stream_index=index, initial_dealer=dealer)


def test_a_deal_is_a_pure_function_of_its_index() -> None:
    left = stream()
    right = stream()
    assert left.stream_id == right.stream_id
    for index in (0, 1, 7, 63, 500):
        assert left.deal(index).hands == right.deal(index).hands
        assert left.deal(index).deal_content_id == right.deal(index).deal_content_id


def test_random_access_needs_no_earlier_deal() -> None:
    """Deal 900 is reachable without generating deals 0 to 899."""

    source = stream()
    far = source.deal(900)
    fresh = MatchStream.build(root_seed="test-stream", stream_index=0, initial_dealer=0)
    assert fresh.deal(900).hands == far.hands
    validate_initial_hands(far.hands)
    assert frozenset(card for hand in far.hands for card in hand) == frozenset(FULL_DECK)


def test_every_deal_is_a_valid_complete_partition() -> None:
    source = stream()
    for index in (0, 3, 40, 41, 129):
        deal = source.deal(index)
        assert len(deal.hands) == 4
        assert all(len(hand) == 13 for hand in deal.hands)
        validate_initial_hands(deal.hands)


def test_prefix_stability_under_extension() -> None:
    """Extending a stream must not disturb any deal already read."""

    source = stream()
    prefix = [source.deal(index).deal_content_id for index in range(12)]
    _ = [source.deal(index) for index in range(12, 400)]
    assert [source.deal(index).deal_content_id for index in range(12)] == prefix
    assert source.prefix_commitment(12) == source.prefix_commitment(12)


def test_chunk_size_cannot_change_a_semantic_result() -> None:
    source = stream()
    reference = [source.deal(index).deal_content_id for index in range(20)]
    for size in (1, 2, 3, 5, 8, 20, 64):
        chunked: list[str] = []
        iterator = source.iter_deals(chunk_size=size)
        for _ in range(20):
            chunked.append(next(iterator).deal_content_id)
        assert chunked == reference, f"chunk size {size} changed the stream"
    assert [item.deal_content_id for item in source.chunk(0, 20)] == reference


def test_chunk_start_offsets_agree_with_direct_access() -> None:
    source = stream()
    assert source.chunk(5, 3)[0].deal_content_id == source.deal(5).deal_content_id
    assert source.chunk(5, 3)[2].deal_content_id == source.deal(7).deal_content_id
    assert [item.deal_index for item in source.chunk(5, 3)] == [5, 6, 7]


def test_streams_are_independent_of_each_other() -> None:
    family = stream_family(root_seed="test-stream", initial_dealer=0, count=6)
    assert len({item.stream_id for item in family}) == 6
    first_deals = {item.deal(0).deal_content_id for item in family}
    assert len(first_deals) == 6


def test_stream_identity_is_semantic_only() -> None:
    base = stream()
    assert base.stream_id.startswith("stream:sha256:")
    assert base.identity_data()["protocol_version"] == STREAM_PROTOCOL_VERSION
    assert stream(index=1).stream_id != base.stream_id
    assert stream(dealer=1).stream_id != base.stream_id
    assert stream(seed="other").stream_id != base.stream_id
    # Nothing operational is part of identity.
    assert set(base.identity_data()) == {
        "generator_id",
        "initial_dealer",
        "protocol_version",
        "root_seed",
        "stream_index",
    }


def test_dealer_rotation_follows_the_ruleset() -> None:
    source = stream(dealer=2)
    dealer = 2
    for index in range(9):
        assert source.expected_dealer(index) == dealer
        dealer = rotate_dealer(dealer)


def test_the_stream_rejects_invalid_addressing() -> None:
    source = stream()
    with pytest.raises(StreamError):
        source.deal(-1)
    with pytest.raises(StreamError):
        source.deal(MAXIMUM_DEAL_INDEX + 1)
    with pytest.raises(StreamError):
        source.chunk(0, 0)
    with pytest.raises(StreamError):
        MatchStream.build(root_seed="x", stream_index=-1, initial_dealer=0)
    with pytest.raises(StreamError):
        MatchStream.build(root_seed="x", stream_index=0, initial_dealer=4)
    with pytest.raises(StreamError):
        MatchStream.build(root_seed="", stream_index=0, initial_dealer=0)


def test_a_forged_stream_identity_is_rejected() -> None:
    source = stream()
    with pytest.raises(StreamError, match="disagrees"):
        MatchStream(
            root_seed=source.root_seed,
            stream_index=source.stream_index,
            initial_dealer=source.initial_dealer,
            stream_id="stream:sha256:" + "0" * 64,
        )


def test_prefix_commitments_detect_a_changed_stream() -> None:
    left = stream(seed="left").prefix_commitment(6)
    right = stream(seed="right").prefix_commitment(6)
    assert left != right
    assert stream(seed="left").prefix_commitment(6) == left
    assert stream(seed="left").prefix_commitment(7) != left
