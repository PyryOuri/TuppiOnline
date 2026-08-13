from __future__ import annotations

import json
import random

import pytest

import tuppi_server.match_runner as match_runner_module
from tuppi_engine import ExplicitDeal
from tuppi_rules import FULL_DECK, card_to_code
from tuppi_server.contract_evaluation import validate_contract_evaluation_record
from tuppi_server.match_runner import LiveMatchRunner


def _deal() -> ExplicitDeal:
    cards = list(FULL_DECK)
    random.Random(260810).shuffle(cards)
    return ExplicitDeal(
        dealer=0,
        hands=tuple(
            tuple(cards[seat * 13 : (seat + 1) * 13])
            for seat in range(4)
        ),
    )


def _runner(monkeypatch: pytest.MonkeyPatch, *, samples: int) -> LiveMatchRunner:
    deal = _deal()

    def fixed_deal(*, dealer: int) -> ExplicitDeal:
        assert dealer == deal.dealer
        return deal

    monkeypatch.setattr(match_runner_module, "generate_live_deal", fixed_deal)
    return LiveMatchRunner(
        match_ref="contract-evaluation-test",
        ai_seats=frozenset({1, 2, 3}),
        contract_rollout_samples=samples,
    )


def test_close_decision_runs_paired_legal_terminal_continuations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(monkeypatch, samples=2)
    evaluations = runner.contract_evaluations_for_deal(0)

    assert [item["seat"] for item in evaluations] == [1, 2, 3]
    close = evaluations[-1]
    assert close["triggered"] is True
    assert close["sample_count"] == 2
    assert close["seed_id"].startswith("contract-eval-v1:")
    assert close["rami"]["requested_contract"] == "RAMI"
    assert close["nolo"]["requested_contract"] == "NOLO"
    assert close["rami"]["sample_count"] == 2
    assert close["nolo"]["sample_count"] == 2
    paired = close["paired"]
    assert (
        paired["rami_better_count"]
        + paired["nolo_better_count"]
        + paired["tie_count"]
        == 2
    )
    assert close["selected_contract"] in {"RAMI", "NOLO"}
    accepted = runner.persistence_record()["accepted_actions"]
    accepted_show = accepted[close["event_index"]]
    assert accepted_show["action"]["declared_contract"] == close["selected_contract"]


def test_evaluation_is_reproducible_and_persists_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _runner(monkeypatch, samples=2)
    first_records = first.contract_evaluations_for_deal(0)
    second = _runner(monkeypatch, samples=2)
    assert second.contract_evaluations_for_deal(0) == first_records

    restored = LiveMatchRunner.from_persistence_record(first.persistence_record())
    assert restored.contract_evaluations_for_deal(0) == first_records
    assert restored.persistence_record() == first.persistence_record()


def test_live_projection_and_aggregate_record_do_not_expose_hidden_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(monkeypatch, samples=2)
    observation = runner.observation(0)
    assert "contract_evaluations" not in observation
    assert "initial_hands" not in observation

    records = runner.contract_evaluations_for_deal(0)
    card_codes = {card_to_code(card) for card in FULL_DECK}

    def strings(value: object):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from strings(item)

    assert not card_codes.intersection(strings(records))
    serialized = json.dumps(records, sort_keys=True)
    for forbidden in ("sampled_hands", "sampled_worlds", "initial_hands"):
        assert forbidden not in serialized


def test_disabled_or_distant_decisions_keep_frozen_heuristic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(monkeypatch, samples=0)
    evaluations = runner.contract_evaluations_for_deal(0)
    assert evaluations
    assert all(item["triggered"] is False for item in evaluations)
    assert all(item["selection_source"] == "heuristic" for item in evaluations)
    assert all(item["sample_count"] == 0 for item in evaluations)
    assert all(item["fallback_reason"] == "evaluation_disabled" for item in evaluations)


def test_contract_evaluation_validator_rejects_private_or_inconsistent_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(monkeypatch, samples=2)
    valid = dict(runner.contract_evaluations_for_deal(0)[-1])

    with_private_data = dict(valid)
    with_private_data["sampled_hands"] = [["AS"]]
    with pytest.raises(ValueError, match="fields"):
        validate_contract_evaluation_record(with_private_data)

    inconsistent = json.loads(json.dumps(valid))
    inconsistent["paired"]["tie_count"] += 1
    with pytest.raises(ValueError, match="counts"):
        validate_contract_evaluation_record(inconsistent)

    invalid_seed = json.loads(json.dumps(valid))
    invalid_seed["seed_id"] = "predictable-seed"
    with pytest.raises(ValueError, match="metadata"):
        validate_contract_evaluation_record(invalid_seed)
