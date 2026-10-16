"""Load research-private synthetic witnesses and replay with the ordinary engine."""

from dataclasses import dataclass
import json
from pathlib import Path

from tuppi_engine import (
    DealState, EnginePhase, ExplicitDeal, PlayCardAction, apply_action,
    create_deal_state, observation_for,
)
from tuppi_engine.errors import EngineValidationError
from tuppi_rules import Card, Contract, FULL_DECK, MatchScore, card_from_code
from tuppi_rules.errors import RulesError
from tuppi_valuation.corpus import forced_show_action

SCHEMA_VERSION = "tuppi.nolo.task_fixtures.v1"


class FixtureError(ValueError):
    """INVALID_INPUT: malformed fixture or engine-illegal history."""


@dataclass(frozen=True)
class ResearchFixture:
    """Private replay inputs, deliberately unsuitable as a policy input."""

    id: str
    dealer: int
    starting_score: MatchScore
    initial_hands: tuple[tuple[Card, ...], ...]
    play_prefix: tuple[tuple[Card, ...], ...]

    def replay(self) -> DealState:
        ref = f"nolo-evidence:{self.id}"
        try:
            state = create_deal_state(
                ExplicitDeal(dealer=self.dealer, hands=self.initial_hands),
                starting_score=self.starting_score, match_ref=ref,
                deal_ref=f"{ref}/deal:0", deal_number=0, event_start_index=0,
            )
            while state.phase is EnginePhase.SHOWING:
                obs = observation_for(state, state.current_actor)
                state = apply_action(state, forced_show_action(obs, Contract.NOLO))
            for group in self.play_prefix:
                for card in group:
                    state = apply_action(state, PlayCardAction(
                        seat=state.current_actor, card=card))
            return state
        except (EngineValidationError, RulesError) as exc:
            raise FixtureError(f"{self.id}: illegal prefix or deal: {exc}") from exc


def _cards(value, label):
    if not isinstance(value, list) or any(not isinstance(c, str) for c in value):
        raise FixtureError(f"{label}: expected a list of card codes")
    try:
        return tuple(card_from_code(c) for c in value)
    except RulesError as exc:
        raise FixtureError(f"{label}: invalid card code: {exc}") from exc


def load_fixtures(path: str | Path) -> tuple[ResearchFixture, ...]:
    """Validate the supplied format, preserving hand order and checking legality.

    Expected answers are intentionally not read into replay objects. Tests read
    those assertions separately; they cannot influence reconstruction.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FixtureError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise FixtureError("unsupported fixture schema version")
    records = data.get("fixtures")
    if not isinstance(records, list) or not records:
        raise FixtureError("fixtures must be a nonempty list")
    fixtures = []
    ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise FixtureError("fixture must be an object")
        name = record.get("id")
        if not isinstance(name, str) or not name or name in ids:
            raise FixtureError("fixture id must be nonempty and unique")
        ids.add(name)
        dealer = record.get("dealer")
        if type(dealer) is not int or dealer not in range(4):
            raise FixtureError(f"{name}: dealer must be an integer in 0..3")
        raw_hands = record.get("initial_hands")
        if not isinstance(raw_hands, list) or len(raw_hands) != 4:
            raise FixtureError(f"{name}: expected four hands")
        hands = tuple(_cards(h, name) for h in raw_hands)
        if any(len(h) != 13 for h in hands):
            raise FixtureError(f"{name}: expected 13 cards per hand")
        if {c for h in hands for c in h} != set(FULL_DECK):
            raise FixtureError(f"{name}: expected 52 unique cards; duplicate/missing card")
        score = record.get("starting_score")
        if not isinstance(score, list) or len(score) != 2:
            raise FixtureError(f"{name}: expected two starting scores")
        try:
            starting_score = MatchScore(*score)
        except RulesError as exc:
            raise FixtureError(f"{name}: invalid starting score: {exc}") from exc
        raw_prefix = record.get("play_prefix")
        if not isinstance(raw_prefix, list) or len(raw_prefix) > 13:
            raise FixtureError(f"{name}: invalid prefix groups")
        prefix = tuple(_cards(g, name) for g in raw_prefix)
        if any(len(g) != 4 for g in prefix[:-1]) or (
            prefix and not 1 <= len(prefix[-1]) <= 4
        ):
            raise FixtureError(f"{name}: only the final prefix group may be partial")
        fixture = ResearchFixture(name, dealer, starting_score, hands, prefix)
        fixture.replay()
        fixtures.append(fixture)
    return tuple(fixtures)
