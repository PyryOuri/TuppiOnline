"""Wire forms under project_target_v2 (sooli) and v3 (sooli + locked bids).

Every observation (every seat, every step), every public event, every deal
result and the match result of random complete matches validate against the
engine schemas; sooli actions round-trip; exchanged cards appear only in the
soolaaja's and the partner's observations; under v3 no bid appears on the wire
before showing resolves.
"""

from __future__ import annotations

import json
from pathlib import Path
import random

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    SooliDecisionAction,
    action_from_data,
    action_to_data,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    deal_result_to_data,
    event_to_data,
    match_observation_for,
    match_result_from_state,
    match_result_to_data,
    observation_to_data,
)
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_rules import Contract, MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK, card_to_code

ROOT = Path(__file__).resolve().parents[2]
V2, V3 = RulesetId.PROJECT_TARGET_V2, RulesetId.PROJECT_TARGET_V3


@pytest.fixture(scope="module")
def validators():
    documents = {path.stem: json.loads(path.read_text(encoding="utf-8"))
                 for path in (ROOT / "schemas/engine").glob("*.json")}
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in documents.values())
    event_schema = {"$ref": documents["public_event_log.schema"]["$id"] + "#/$defs/event"}
    return {
        "observation": Draft202012Validator(documents["player_observation.schema"], registry=registry),
        "event": Draft202012Validator(event_schema, registry=registry),
        "deal": Draft202012Validator(documents["deal_result.schema"], registry=registry),
        "match": Draft202012Validator(documents["match_result.schema"], registry=registry),
    }


def _choose(state, rng):
    actor = state.current_actor
    legal = match_observation_for(state, actor).legal_actions
    if state.phase is EnginePhase.SHOWING:
        nolo = [a for a in legal if a.declared_contract is Contract.NOLO]
        rami = [a for a in legal if a.declared_contract is Contract.RAMI]
        return rng.choice(nolo if nolo and (rng.random() < 0.5 or not rami) else rami)
    if state.phase is EnginePhase.SOOLI_OFFER:
        return SooliDecisionAction(seat=actor, play_sooli=rng.random() < 0.6)
    return rng.choice(legal)


def _new_deal(rng, dealer):
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    return ExplicitDeal(dealer=dealer, hands=tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4)))


@pytest.mark.parametrize("ruleset", [V2, V3])
def test_random_matches_serialize_to_valid_wire_data(validators, ruleset):
    rng = random.Random(f"wire-{ruleset.value}")
    sooli_deals = 0
    for match in range(3):
        state = create_match(initial_score=MatchScore(0, 0), initial_dealer=match % 4,
                             match_ref=f"wire-{match}", ruleset_id=ruleset)
        seen_events = 0
        while not state.terminal:
            state = begin_explicit_deal(state, _new_deal(rng, state.dealer))
            while state.phase in ACTIVE_PHASES:
                deal = state.active_deal
                for seat in range(4):
                    data = observation_to_data(match_observation_for(state, seat))
                    validators["observation"].validate(data)
                    assert data["ruleset_id"] == ruleset.value
                    knows = deal.soolaaja is not None and seat in (deal.soolaaja, (deal.soolaaja + 2) % 4)
                    if not knows:
                        assert data["sooli"]["given_card"] is None and data["sooli"]["returned_card"] is None
                    if ruleset is V3 and state.phase is EnginePhase.SHOWING:
                        text = json.dumps(data)
                        for show in deal.show_actions:
                            if show.seat != seat:
                                assert f'"{card_to_code(show.shown_card)}"' not in text.replace(
                                    json.dumps(data["own_hand"]), "")
                for action in match_observation_for(state, state.current_actor).legal_actions:
                    assert action_from_data(action_to_data(action)) == action
                state = apply_match_action(state, _choose(state, rng))
                for event in state.public_events[seen_events:]:
                    validators["event"].validate(event_to_data(event))
                seen_events = len(state.public_events)
            result = state.completed_deals[-1].public_result
            sooli_deals += result.soolaaja is not None
            validators["deal"].validate(deal_result_to_data(result))
        validators["match"].validate(match_result_to_data(match_result_from_state(state)))
    assert sooli_deals > 0


def test_v1_wire_data_is_unchanged():
    """v1 observations keep exactly their original keys."""
    rng = random.Random("wire-v1")
    state = begin_explicit_deal(
        create_match(initial_score=MatchScore(0, 0), initial_dealer=0, match_ref="wire-v1"),
        _new_deal(rng, 0))
    data = observation_to_data(match_observation_for(state, 1))
    assert "sooli" not in data and "bids_locked" not in data
