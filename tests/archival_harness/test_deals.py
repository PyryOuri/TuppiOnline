from __future__ import annotations

import json
import random

import pytest

from tuppi_legacy.constants import CARD_ENCODING, DEAL_SCHEMA_VERSION
from tuppi_legacy.deals import (
    Deal,
    compute_deal_id,
    deal_set_to_dict,
    generate_deals,
    load_deals,
    make_deal,
    validate_deal,
)
from tuppi_legacy.errors import DealValidationError


def test_generated_deal_is_complete_and_does_not_advance_global_rng() -> None:
    random.seed(9001)
    before = random.getstate()
    deal = generate_deals(count=1, seed=1729, initial_dealer=0)[0]
    after = random.getstate()
    assert before == after
    assert len(deal.hands) == 4
    assert all(len(hand) == 13 for hand in deal.hands)
    assert sorted(card for hand in deal.hands for card in hand) == list(range(52))
    assert deal.deal_id == "sha256:7e19723378d72b24bbef3748ee8002ef61b2a245c4a586ce7d5b26576f9f0ac1"


def test_deal_id_excludes_provenance_but_includes_cards_and_dealer(example_deal) -> None:
    original = compute_deal_id(example_deal.hands, example_deal.dealer)
    copy = make_deal(
        hands=example_deal.hands,
        dealer=example_deal.dealer,
        source={"kind": "explicit", "label": "a different provenance"},
    )
    assert copy.deal_id == original == example_deal.deal_id
    changed_dealer = make_deal(
        hands=example_deal.hands,
        dealer=1,
        source={"kind": "explicit"},
    )
    assert changed_dealer.deal_id != original


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda value: value["hands"][0].pop(), "exactly 13"),
        (lambda value: value["hands"][1].__setitem__(0, value["hands"][0][0]), "exactly once"),
        (lambda value: value["hands"][0].__setitem__(0, 52), "0..51"),
        (lambda value: value["hands"][0].__setitem__(0, True), "0..51"),
        (lambda value: value.__setitem__("dealer", 4), "0..3"),
        (lambda value: value.__setitem__("card_encoding", "unknown"), "card_encoding"),
        (lambda value: value.__setitem__("deal_id", "sha256:" + "0" * 64), "mismatch"),
    ],
)
def test_invalid_deal_files_are_rejected(tmp_path, example_deal, mutator, message) -> None:
    value = example_deal.to_dict()
    mutator(value)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(DealValidationError, match=message):
        load_deals(path)


def test_malformed_json_is_rejected(tmp_path) -> None:
    path = tmp_path / "malformed.json"
    path.write_text('{"schema_version":', encoding="utf-8")
    with pytest.raises(DealValidationError, match="not valid JSON"):
        load_deals(path)


def test_unknown_or_missing_deal_fields_are_rejected(tmp_path, example_deal) -> None:
    value = example_deal.to_dict()
    value["unexpected"] = 1
    path = tmp_path / "extra.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(DealValidationError, match="unknown"):
        load_deals(path)

    del value["unexpected"]
    del value["source"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(DealValidationError, match="missing"):
        load_deals(path)


def test_required_deal_metadata_is_serialized(example_deal) -> None:
    value = example_deal.to_dict()
    assert value["schema_version"] == DEAL_SCHEMA_VERSION
    assert value["card_encoding"] == CARD_ENCODING
    assert value["deal_id"].startswith("sha256:")
    assert value["source"]["seed"] == 1729


def test_explicit_deal_set_round_trips(tmp_path, example_deal) -> None:
    path = tmp_path / "set.json"
    path.write_text(
        json.dumps(deal_set_to_dict([example_deal])), encoding="utf-8"
    )
    assert load_deals(path) == [example_deal]


def test_programmatically_constructed_invalid_deal_is_revalidated(example_deal) -> None:
    invalid = Deal(
        deal_id=example_deal.deal_id,
        hands=example_deal.hands[:3],
        dealer=example_deal.dealer,
        source=example_deal.source,
    )
    with pytest.raises(DealValidationError, match="four ordered hands"):
        validate_deal(invalid)
