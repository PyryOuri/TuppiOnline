"""Immutable public and research-private engine result records."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from tuppi_rules import (
    Card,
    Contract,
    DealScore,
    MatchScore,
    RulesError,
    RulesetId,
    ShowAction as RulesShowAction,
    Team,
    first_leader,
    forehand,
    is_match_terminal,
    match_winner,
    resolve_showing,
    rotate_dealer,
    score_nolo,
    score_rami_for_declarer,
    transition_rising_score,
    validate_completed_deal,
    validate_deal_score,
    validate_initial_hands,
    validate_show_action,
)

from .deal import ExplicitDeal
from .errors import StateInvariantError
from .event_builder import build_expected_deal_events
from .events import DealOutcome, PublicEvent
from .state import CompletedTrick
from .validation import (
    expected_deal_ref,
    is_sha256_identifier,
    is_valid_deal_ref,
    is_valid_match_ref,
)


DEAL_RESULT_SCHEMA_VERSION = "tuppi.engine.deal_result.v1"
MATCH_RESULT_SCHEMA_VERSION = "tuppi.engine.match_result.v1"
RESEARCH_RESULT_SCHEMA_VERSION = "tuppi.engine.research_result.v1"


@dataclass(frozen=True, slots=True)
class DealResult:
    match_ref: str
    deal_ref: str
    deal_number: int
    dealer: int
    forehand: int
    contract: Contract
    declarer: int | None
    first_leader: int
    show_actions: tuple[RulesShowAction, ...]
    completed_tricks: tuple[CompletedTrick, ...]
    team_tricks: tuple[int, int]
    deal_score: DealScore
    outcome: DealOutcome
    score_before: MatchScore
    score_after: MatchScore
    match_terminal: bool
    next_dealer: int | None
    events: tuple[PublicEvent, ...]
    schema_version: str = field(default=DEAL_RESULT_SCHEMA_VERSION, init=False)
    ruleset_id: RulesetId = field(default=RulesetId.PROJECT_TARGET_V1, init=False)

    def __post_init__(self) -> None:
        try:
            self._validate()
        except StateInvariantError:
            raise
        except RulesError as exc:
            raise StateInvariantError(
                f"deal result violates project_target_v1: {exc}"
            ) from exc
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise StateInvariantError("deal result contains malformed fields") from exc

    def _validate(self) -> None:
        if not is_valid_match_ref(self.match_ref) or not is_valid_deal_ref(self.deal_ref):
            raise StateInvariantError("result references do not match the public schema")
        if type(self.deal_number) is not int or self.deal_number < 0:
            raise StateInvariantError("deal_number must be nonnegative")
        if self.deal_ref != expected_deal_ref(self.match_ref, self.deal_number):
            raise StateInvariantError("deal_ref disagrees with match_ref or deal_number")
        if type(self.dealer) is not int or self.dealer not in range(4):
            raise StateInvariantError("result dealer must be in 0..3")
        if type(self.forehand) is not int or self.forehand not in range(4):
            raise StateInvariantError("result forehand must be in 0..3")
        if self.forehand != forehand(self.dealer):
            raise StateInvariantError("result forehand disagrees with dealer")
        if not isinstance(self.contract, Contract):
            raise StateInvariantError("result contract must be a Contract")
        if self.contract is Contract.RAMI:
            if type(self.declarer) is not int or self.declarer not in range(4):
                raise StateInvariantError("RAMI result requires a declarer")
        elif self.declarer is not None:
            raise StateInvariantError("NOLO result must not have a declarer")
        if type(self.first_leader) is not int or self.first_leader not in range(4):
            raise StateInvariantError("result first_leader must be in 0..3")
        if (
            type(self.show_actions) is not tuple
            or not self.show_actions
            or any(not isinstance(action, RulesShowAction) for action in self.show_actions)
        ):
            raise StateInvariantError("result must contain ordered show actions")
        if (
            type(self.completed_tricks) is not tuple
            or len(self.completed_tricks) != 13
            or any(not isinstance(trick, CompletedTrick) for trick in self.completed_tricks)
        ):
            raise StateInvariantError("result must contain exactly 13 completed tricks")
        if tuple(trick.trick_index for trick in self.completed_tricks) != tuple(range(13)):
            raise StateInvariantError("result trick indices must be exactly 0 through 12")
        for trick in self.completed_tricks:
            if CompletedTrick(
                trick_index=trick.trick_index,
                leader=trick.leader,
                plays=trick.plays,
                winner=trick.winner,
            ) != trick:
                raise StateInvariantError("result completed trick contains invalid fields")
        checked_deal_score = validate_deal_score(self.deal_score)
        if checked_deal_score != self.deal_score:
            raise StateInvariantError("result deal score contains invalid fields")
        if (
            type(self.team_tricks) is not tuple
            or len(self.team_tricks) != 2
            or any(type(value) is not int for value in self.team_tricks)
        ):
            raise StateInvariantError("result team_tricks must be an integer pair")
        if self.team_tricks != self.deal_score.team_tricks or sum(self.team_tricks) != 13:
            raise StateInvariantError("result trick totals disagree with score")
        if not isinstance(self.outcome, DealOutcome):
            raise StateInvariantError("result outcome must be a DealOutcome")
        if not isinstance(self.score_before, MatchScore) or not isinstance(
            self.score_after, MatchScore
        ):
            raise StateInvariantError("result scores must be MatchScore values")
        if MatchScore(self.score_before.team0, self.score_before.team1) != self.score_before:
            raise StateInvariantError("result score_before contains invalid fields")
        if MatchScore(self.score_after.team0, self.score_after.team1) != self.score_after:
            raise StateInvariantError("result score_after contains invalid fields")
        if type(self.match_terminal) is not bool or self.match_terminal != is_match_terminal(
            self.score_after
        ):
            raise StateInvariantError("result terminal flag disagrees with score")
        if self.match_terminal:
            if self.next_dealer is not None:
                raise StateInvariantError("terminal result cannot rotate dealer")
        elif type(self.next_dealer) is not int or self.next_dealer not in range(4):
            raise StateInvariantError("nonterminal result requires the next dealer")
        elif self.next_dealer != rotate_dealer(self.dealer):
            raise StateInvariantError("nonterminal result next dealer is invalid")
        if (
            type(self.events) is not tuple
            or not self.events
            or any(not isinstance(event, PublicEvent) for event in self.events)
        ):
            raise StateInvariantError("result requires immutable public events")
        if self.deal_score.contract is not self.contract:
            raise StateInvariantError("result contract disagrees with deal score")
        expected_outcome = (
            DealOutcome.NOLO
            if self.contract is Contract.NOLO
            else DealOutcome.STOLEN_RAMI
            if self.deal_score.stolen_rami
            else DealOutcome.MADE_RAMI
        )
        if self.outcome is not expected_outcome:
            raise StateInvariantError("result outcome disagrees with deal score")
        expected_deal_score = (
            score_nolo(*self.team_tricks)
            if self.contract is Contract.NOLO
            else score_rami_for_declarer(self.declarer, *self.team_tricks)
        )
        if self.deal_score != expected_deal_score:
            raise StateInvariantError("result deal score disagrees with contract/declarer")
        if first_leader(
            contract=self.contract,
            dealer=self.dealer,
            declarer=self.declarer,
        ) != self.first_leader:
            raise StateInvariantError("result first leader is invalid")
        if transition_rising_score(self.score_before, self.deal_score) != self.score_after:
            raise StateInvariantError("result score transition is invalid")
        resolution = resolve_showing(dealer=self.dealer, actions=self.show_actions)
        if resolution.contract is not self.contract or resolution.declarer != self.declarer:
            raise StateInvariantError("result showing resolution is invalid")
        validated_totals = validate_completed_deal(
            tuple(trick.plays for trick in self.completed_tricks),
            expected_first_leader=self.first_leader,
        )
        if validated_totals != self.team_tricks:
            raise StateInvariantError("result transcript trick totals are invalid")
        played_by_card = {
            play.card: play.seat
            for trick in self.completed_tricks
            for play in trick.plays
        }
        if any(
            played_by_card.get(show.shown_card) != show.seat
            for show in self.show_actions
        ):
            raise StateInvariantError(
                "shown-card ownership disagrees with the play transcript"
            )
        expected_events = build_expected_deal_events(
            event_start_index=self.events[0].event_index,
            match_ref=self.match_ref,
            deal_ref=self.deal_ref,
            deal_number=self.deal_number,
            dealer=self.dealer,
            forehand_seat=self.forehand,
            score_before=self.score_before,
            show_actions=self.show_actions,
            contract=self.contract,
            declarer=self.declarer,
            first_leader_seat=self.first_leader,
            completed_tricks=self.completed_tricks,
            current_trick=(),
            team_tricks=self.team_tricks,
            deal_score=self.deal_score,
            score_after=self.score_after,
            next_dealer=self.next_dealer,
        )
        if self.events != expected_events:
            raise StateInvariantError("result events disagree with its public transcript")


@dataclass(frozen=True, slots=True)
class ResearchDealResult:
    """Private research wrapper; never pass this object to an agent."""

    public_result: DealResult
    deal_id: str
    initial_hands: tuple[tuple[Card, ...], ...]

    def __post_init__(self) -> None:
        try:
            self._validate()
        except StateInvariantError:
            raise
        except RulesError as exc:
            raise StateInvariantError(
                f"research deal violates project_target_v1: {exc}"
            ) from exc
        except (AttributeError, IndexError, TypeError, ValueError) as exc:
            raise StateInvariantError("research deal contains malformed fields") from exc

    def _validate(self) -> None:
        if not isinstance(self.public_result, DealResult):
            raise StateInvariantError("public_result must be a DealResult")
        hands = validate_initial_hands(self.initial_hands)
        checked = ExplicitDeal(
            dealer=self.public_result.dealer,
            hands=hands,
            claimed_deal_id=self.deal_id,
        )
        if checked.hands != self.initial_hands:
            raise StateInvariantError("research hands must be immutable ordered tuples")
        for show in self.public_result.show_actions:
            expected = validate_show_action(
                seat=show.seat,
                hand=hands[show.seat],
                shown_card=show.shown_card,
                declared_contract=show.declared_contract,
                claimed_verbal_required=show.verbal_required,
            )
            if show != expected:
                raise StateInvariantError("research show is not valid for its initial hand")
        for seat in range(4):
            played = tuple(
                play.card
                for trick in self.public_result.completed_tricks
                for play in trick.plays
                if play.seat == seat
            )
            if len(played) != 13 or frozenset(played) != frozenset(hands[seat]):
                raise StateInvariantError(
                    "research initial ownership disagrees with public transcript"
                )


@dataclass(frozen=True, slots=True)
class MatchResult:
    match_ref: str
    initial_score: MatchScore
    initial_dealer: int
    final_score: MatchScore
    winner_team: Team
    deals: tuple[DealResult, ...]
    events: tuple[PublicEvent, ...]
    schema_version: str = field(default=MATCH_RESULT_SCHEMA_VERSION, init=False)
    ruleset_id: RulesetId = field(default=RulesetId.PROJECT_TARGET_V1, init=False)

    def __post_init__(self) -> None:
        if not is_valid_match_ref(self.match_ref):
            raise StateInvariantError("match_ref does not match the public schema")
        if not isinstance(self.initial_score, MatchScore) or is_match_terminal(
            self.initial_score
        ):
            raise StateInvariantError("initial_score must be nonterminal")
        if type(self.initial_dealer) is not int or self.initial_dealer not in range(4):
            raise StateInvariantError("initial_dealer must be in 0..3")
        if not isinstance(self.final_score, MatchScore) or not is_match_terminal(
            self.final_score
        ):
            raise StateInvariantError("final_score must be terminal")
        if match_winner(self.final_score) is not self.winner_team:
            raise StateInvariantError("winner_team disagrees with final score")
        if type(self.deals) is not tuple or not self.deals:
            raise StateInvariantError("terminal match result requires completed deals")
        if self.deals[-1].score_after != self.final_score:
            raise StateInvariantError("last deal score disagrees with final match score")
        if type(self.events) is not tuple or not self.events:
            raise StateInvariantError("match result requires public events")
        if tuple(event.event_index for event in self.events) != tuple(
            range(len(self.events))
        ):
            raise StateInvariantError("match event indices must be contiguous from zero")
        for index, deal in enumerate(self.deals):
            if deal.deal_number != index or deal.match_ref != self.match_ref:
                raise StateInvariantError("match deal order or reference is invalid")
            if index == 0:
                if deal.score_before != self.initial_score or deal.dealer != self.initial_dealer:
                    raise StateInvariantError("first deal disagrees with initial match state")
            else:
                previous = self.deals[index - 1]
                if deal.score_before != previous.score_after or deal.dealer != previous.next_dealer:
                    raise StateInvariantError("match result deal sequence is discontinuous")
        expected_events = tuple(event for deal in self.deals for event in deal.events)
        if self.events != expected_events:
            raise StateInvariantError("match result events disagree with deal results")


@dataclass(frozen=True, slots=True)
class ResearchRunResult:
    """Canonical full-information result for an explicit finite run."""

    match_input_id: str
    match_ref: str
    initial_score: MatchScore
    initial_dealer: int
    agent_ids: tuple[str, str, str, str]
    deals: tuple[ResearchDealResult, ...]
    final_score: MatchScore
    next_dealer: int | None
    terminal: bool
    match_result: MatchResult | None
    public_events: tuple[PublicEvent, ...]
    schema_version: str = field(default=RESEARCH_RESULT_SCHEMA_VERSION, init=False)
    ruleset_id: RulesetId = field(default=RulesetId.PROJECT_TARGET_V1, init=False)
    visibility: str = field(default="research_private", init=False)
    contains_hidden_information: bool = field(default=True, init=False)
    execution_status: str = field(default="success", init=False)

    def __post_init__(self) -> None:
        if not is_sha256_identifier(self.match_input_id):
            raise StateInvariantError("match_input_id must be a sha256 identifier")
        if not is_valid_match_ref(self.match_ref):
            raise StateInvariantError("match_ref does not match the public schema")
        if not isinstance(self.initial_score, MatchScore) or not isinstance(
            self.final_score, MatchScore
        ):
            raise StateInvariantError("research result scores must be MatchScore values")
        if type(self.initial_dealer) is not int or self.initial_dealer not in range(4):
            raise StateInvariantError("initial_dealer must be in 0..3")
        if type(self.agent_ids) is not tuple or len(self.agent_ids) != 4 or any(
            not isinstance(identity, str) or not identity for identity in self.agent_ids
        ):
            raise StateInvariantError("exactly four nonempty agent identities are required")
        if type(self.deals) is not tuple or not self.deals:
            raise StateInvariantError("research result requires at least one completed deal")
        if any(not isinstance(deal, ResearchDealResult) for deal in self.deals):
            raise StateInvariantError("research deals must be ResearchDealResult values")
        if type(self.terminal) is not bool or self.terminal != is_match_terminal(
            self.final_score
        ):
            raise StateInvariantError("terminal flag disagrees with final score")
        if self.terminal:
            if self.match_result is None or self.next_dealer is not None:
                raise StateInvariantError("terminal run requires MatchResult and no next dealer")
        elif self.match_result is not None or type(self.next_dealer) is not int:
            raise StateInvariantError("nonterminal run requires a next dealer and no MatchResult")
        if type(self.public_events) is not tuple:
            raise StateInvariantError("public_events must be an immutable tuple")
        if tuple(event.event_index for event in self.public_events) != tuple(
            range(len(self.public_events))
        ):
            raise StateInvariantError(
                "research event indices must be contiguous from zero"
            )
        public_deals = tuple(deal.public_result for deal in self.deals)
        for index, deal in enumerate(public_deals):
            if deal.deal_number != index or deal.match_ref != self.match_ref:
                raise StateInvariantError("research deal order or match reference is invalid")
            if index == 0:
                if deal.dealer != self.initial_dealer or deal.score_before != self.initial_score:
                    raise StateInvariantError("first research deal disagrees with initial state")
            else:
                previous = public_deals[index - 1]
                if previous.match_terminal:
                    raise StateInvariantError("research deal follows a terminal result")
                if deal.dealer != previous.next_dealer or deal.score_before != previous.score_after:
                    raise StateInvariantError("research deal sequence is discontinuous")
        if public_deals[-1].score_after != self.final_score:
            raise StateInvariantError("research final score disagrees with last deal")
        expected_events = tuple(
            event for deal in public_deals for event in deal.events
        )
        if self.public_events != expected_events:
            raise StateInvariantError("research public events disagree with deal results")
        explicit_deals = tuple(
            ExplicitDeal(
                dealer=deal.public_result.dealer,
                hands=deal.initial_hands,
                claimed_deal_id=deal.deal_id,
            )
            for deal in self.deals
        )
        expected_input_id = calculate_match_input_id(
            initial_score=self.initial_score,
            initial_dealer=self.initial_dealer,
            deals=explicit_deals,
        )
        if self.match_input_id != expected_input_id:
            raise StateInvariantError("match_input_id disagrees with research deals")
        if self.terminal:
            expected_match = MatchResult(
                match_ref=self.match_ref,
                initial_score=self.initial_score,
                initial_dealer=self.initial_dealer,
                final_score=self.final_score,
                winner_team=match_winner(self.final_score),
                deals=public_deals,
                events=self.public_events,
            )
            if self.match_result != expected_match:
                raise StateInvariantError("terminal MatchResult disagrees with research run")
        elif self.next_dealer != public_deals[-1].next_dealer:
            raise StateInvariantError("research next dealer disagrees with last result")


def calculate_match_input_id(
    *,
    initial_score: MatchScore,
    initial_dealer: int,
    deals: tuple[ExplicitDeal, ...],
) -> str:
    """Content identity shared by strict input and research-result validation."""

    identity = {
        "deal_ids": [deal.deal_id for deal in deals],
        "initial_dealer": initial_dealer,
        "initial_score": [initial_score.team0, initial_score.team1],
        "ruleset_id": RulesetId.PROJECT_TARGET_V1.value,
        "schema_version": "tuppi.engine.match_input_identity.v1",
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
