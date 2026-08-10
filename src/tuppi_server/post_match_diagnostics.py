"""Deterministic post-match diagnostics over authoritative match history.

This module is deliberately server-only.  It reconstructs every historical
decision from the persisted explicit deals and accepted actions, gives the
frozen reference policy only the player's formal observation, and invokes the
Phase 5B perfect-information solver only after the match is terminal.

It does not import any of the failed Phase 5 search or belief agents.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Mapping

from tuppi_agents import (
    construct_registered_agent,
    phase4_specifications_by_profile_key,
)
from tuppi_engine import (
    Action,
    EnginePhase,
    MatchState,
    PlayCardAction,
    PlayerObservation,
    ShowAction,
    action_from_data,
    action_to_data,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    deal_result_to_data,
    event_to_data,
    explicit_deal_from_data,
    match_observation_for,
)
from tuppi_exact import SolverBudgetError, SolverError, solve_late_game
from tuppi_rules import (
    Contract,
    MatchScore,
    PlayedCard,
    card_to_code,
    partner_for_seat,
    team_for_seat,
    trick_winner,
)

from .analysis import (
    COMPLETED_DEAL_DIAGNOSTICS_SCHEMA_VERSION,
    POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION,
    validate_completed_deal_analysis_response,
    validate_post_match_analysis_response,
)
from .match_runner import LiveMatchRunner
from .projection import project_event_batch, project_match_result


REFERENCE_PROFILE_KEY = "partner_aware_v1"
EXACT_SOURCE_ID = "phase5b_exact_late_game_v1"
RULE_SOURCE_ID = "deterministic_tactical_rules_v1"
REFERENCE_SOURCE_ID = REFERENCE_PROFILE_KEY
MAX_DIAGNOSTICS = 10


@dataclass(frozen=True, slots=True)
class HistoricalDecision:
    """One accepted action and the exact state immediately before it."""

    action_index: int
    event_index: int
    state: MatchState
    observation: PlayerObservation
    action: Action

    @property
    def deal_state(self):
        active = self.state.active_deal
        if active is None:  # pragma: no cover - guarded during reconstruction
            raise RuntimeError("historical decision has no active deal")
        return active


@dataclass(frozen=True, slots=True)
class _Candidate:
    priority: int
    item: dict[str, object]


def reconstruct_historical_decisions(
    runner: LiveMatchRunner,
    *,
    seat: int,
    deal_number: int | None = None,
) -> tuple[HistoricalDecision, ...]:
    """Replay durable private material and recover ``seat``'s formal inputs.

    Replaying from the persisted explicit deals is important: deriving a past
    observation from the final state would silently grant the reference policy
    knowledge that was unavailable when the action was taken.
    """

    if not isinstance(runner, LiveMatchRunner):
        raise TypeError("historical reconstruction requires a LiveMatchRunner")
    if type(seat) is not int or seat not in range(4):
        raise ValueError("analysis seat must be an integer in 0..3")
    if deal_number is None and not runner.terminal:
        raise ValueError("post-match reconstruction requires a terminal match")
    if deal_number is not None and (
        type(deal_number) is not int
        or deal_number < 0
        or deal_number >= len(runner.state.completed_deals)
    ):
        raise ValueError("completed-deal reconstruction requires a completed deal")

    record = runner.persistence_record()
    initial_score = record["initial_score"]
    if type(initial_score) is not list or len(initial_score) != 2:
        raise ValueError("persisted initial score is invalid")
    state = create_match(
        initial_score=MatchScore(initial_score[0], initial_score[1]),
        initial_dealer=record["initial_dealer"],
        match_ref=record["match_ref"],
    )
    deals = tuple(explicit_deal_from_data(item) for item in record["deals"])
    if not deals:
        raise ValueError("terminal match has no persisted deals")
    next_deal = 0

    def start_next_deal() -> None:
        nonlocal state, next_deal
        if next_deal >= len(deals):
            raise ValueError("accepted actions require a missing persisted deal")
        state = begin_explicit_deal(state, deals[next_deal])
        next_deal += 1

    start_next_deal()
    decisions: list[HistoricalDecision] = []
    actions = record["accepted_actions"]
    if type(actions) is not list:
        raise ValueError("persisted accepted actions are invalid")
    for expected_action_index, raw_record in enumerate(actions):
        if type(raw_record) is not dict:
            raise ValueError("persisted accepted action is invalid")
        if state.phase is EnginePhase.DEAL_COMPLETE:
            start_next_deal()
        action = action_from_data(raw_record["action"])
        action_index = raw_record["action_index"]
        if action_index != expected_action_index:
            raise ValueError("persisted action indices are not contiguous")
        if state.current_actor != action.seat:
            raise ValueError("persisted action actor disagrees with replay state")

        before = state
        observation = match_observation_for(before, action.seat)
        if action not in observation.legal_actions:
            raise ValueError("persisted action is absent from historical legal actions")
        previous_event_count = len(before.public_events)
        state = apply_match_action(before, action)
        accepted_events = tuple(
            event_to_data(event)
            for event in state.public_events[previous_event_count:]
            if (
                isinstance(action, ShowAction)
                and event.event_type.value == "show_accepted"
            )
            or (
                isinstance(action, PlayCardAction)
                and event.event_type.value == "card_played"
            )
        )
        if len(accepted_events) != 1:
            raise ValueError("accepted action did not produce one public action event")
        event_index = accepted_events[0]["event_index"]
        if type(event_index) is not int:
            raise ValueError("accepted action event index is invalid")
        if action.seat == seat and (
            deal_number is None or before.active_deal.deal_number == deal_number
        ):
            decisions.append(
                HistoricalDecision(
                    action_index=action_index,
                    event_index=event_index,
                    state=before,
                    observation=observation,
                    action=action,
                )
            )

        if (
            deal_number is not None
            and before.active_deal.deal_number == deal_number
            and len(state.completed_deals) > deal_number
        ):
            break

    if deal_number is None:
        if not state.terminal:
            raise ValueError("persisted accepted actions do not reach a terminal match")
        if project_event_batch(state.public_events) != record["public_events"]:
            raise ValueError("historical reconstruction disagrees with public history")
        if state.score != runner.state.score:
            raise ValueError("historical reconstruction disagrees with final score")
    elif (
        len(state.completed_deals) <= deal_number
        or state.completed_deals[deal_number].public_result
        != runner.state.completed_deals[deal_number].public_result
    ):
        raise ValueError("historical reconstruction disagrees with completed deal")
    return tuple(decisions)


def generate_post_match_diagnostics(
    runner: LiveMatchRunner,
    *,
    seat: int,
) -> dict[str, object]:
    """Generate and validate the real, seat-scoped post-match response."""

    decisions = reconstruct_historical_decisions(runner, seat=seat)
    selected = _selected_diagnostics(decisions, runner=runner, seat=seat)
    result = project_match_result(runner.state)
    response: dict[str, object] = {
        "schema_version": POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION,
        "match_ref": runner.match_ref,
        "seat": seat,
        "summary": {
            "deal_count": len(runner.state.completed_deals),
            "diagnostic_count": len(selected),
            "final_score": result["final_score"],
            "winner_team": result["winner_team"],
        },
        "analyses": selected,
    }
    return validate_post_match_analysis_response(
        response,
        expected_match_ref=runner.match_ref,
        public_events=project_event_batch(runner.state.public_events),
    )


def generate_completed_deal_diagnostics(
    runner: LiveMatchRunner,
    *,
    seat: int,
    deal_number: int,
) -> dict[str, object]:
    """Generate diagnostics for one completed deal without waiting for 52."""

    decisions = reconstruct_historical_decisions(
        runner,
        seat=seat,
        deal_number=deal_number,
    )
    selected = _selected_diagnostics(decisions, runner=runner, seat=seat)
    result = deal_result_to_data(
        runner.state.completed_deals[deal_number].public_result
    )
    response: dict[str, object] = {
        "schema_version": COMPLETED_DEAL_DIAGNOSTICS_SCHEMA_VERSION,
        "match_ref": runner.match_ref,
        "deal_ref": result["deal_ref"],
        "deal_number": deal_number,
        "seat": seat,
        "summary": {
            "contract": result["contract"],
            "diagnostic_count": len(selected),
            "outcome": result["outcome"],
            "points": result["deal_score"]["points"],
            "score_before": result["score_before"],
            "score_after": result["score_after"],
            "team_tricks": result["team_tricks"],
        },
        "analyses": selected,
    }
    return validate_completed_deal_analysis_response(
        response,
        expected_match_ref=runner.match_ref,
        expected_deal_number=deal_number,
        public_events=result["events"],
    )


def _selected_diagnostics(
    decisions: tuple[HistoricalDecision, ...],
    *,
    runner: LiveMatchRunner,
    seat: int,
) -> list[dict[str, object]]:
    specification = phase4_specifications_by_profile_key()[REFERENCE_PROFILE_KEY]
    reference = construct_registered_agent(specification, seat=seat)
    candidates: list[_Candidate] = []
    for decision in decisions:
        exact = _exact_candidate(decision)
        if exact is not None:
            candidates.append(exact)
            continue
        rule = _rule_candidate(decision, runner)
        if rule is not None:
            candidates.append(rule)
            continue
        preferred = reference.choose_action(decision.observation)
        if preferred != decision.action:
            candidates.append(_reference_candidate(decision, preferred))
    candidates.sort(
        key=lambda candidate: (-candidate.priority, candidate.item["event_index"])
    )
    selected = [candidate.item for candidate in _rank_useful_candidates(candidates)]
    selected.sort(key=lambda item: item["event_index"])
    return selected


def _rank_useful_candidates(candidates: list[_Candidate]) -> list[_Candidate]:
    """Apply evidence priority while preserving a small amount of source breadth."""

    exact = [item for item in candidates if item.item["source"] == "Exact"]
    rules = [item for item in candidates if item.item["source"] == "Rule-based"]
    references = [item for item in candidates if item.item["source"] == "Reference"]
    selected = exact[:MAX_DIAGNOSTICS]
    remaining = MAX_DIAGNOSTICS - len(selected)
    if remaining <= 0:
        return selected

    # Exact evidence is never displaced.  With room left, retain up to four
    # objective tactical findings and, when available, at least one explicitly
    # labelled reference comparison instead of returning ten near-duplicates.
    reserve_reference = 1 if references else 0
    rule_count = min(4, max(0, remaining - reserve_reference), len(rules))
    selected.extend(rules[:rule_count])
    remaining = MAX_DIAGNOSTICS - len(selected)
    selected.extend(references[:remaining])
    remaining = MAX_DIAGNOSTICS - len(selected)
    if remaining:
        selected.extend(rules[rule_count : rule_count + remaining])
    return selected


def _exact_candidate(decision: HistoricalDecision) -> _Candidate | None:
    if not isinstance(decision.action, PlayCardAction):
        return None
    state = decision.deal_state
    if len(state.completed_tricks) < 9 or len(decision.observation.legal_actions) < 2:
        return None
    try:
        solution = solve_late_game(state, maximum_tricks_remaining=4)
    except (SolverBudgetError, SolverError):
        return None
    regret = solution.regret_in_tricks(decision.action.card)
    if regret <= 0:
        return None

    best_card = solution.optimal_cards[0]
    suggested = PlayCardAction(seat=decision.action.seat, card=best_card)
    chosen_value = solution.value_for(decision.action.card).own_team_tricks_final
    best_value = solution.optimal_own_team_tricks_final
    direction = "enemmän" if solution.own_team_prefers_more_tricks else "vähemmän"
    text = (
        f"Täydellisen tiedon loppupelissä {card_to_code(best_card)} johtaa "
        f"oman parin kannalta {regret} tikin parempaan tulokseen."
    )
    return _Candidate(
        priority=1000 + regret * 20 + _late_importance(decision),
        item=_item(
            decision,
            source="Exact",
            confidence="perfect_information_exact",
            source_id=EXACT_SOURCE_ID,
            reason_code="exact_late_game_trick_loss",
            title="Mitattava loppupeliero",
            summary=text,
            recommended=suggested,
            recommendation=(
                f"Pelaa {card_to_code(best_card)}: optimaalinen loppuarvo on "
                f"{best_value} tikkiä ({direction} on tässä sopimuksessa parempi)."
            ),
            explanation=(
                "Phase 5B -ratkaisija vertasi kaikki lailliset kortit valmiin jaon täydellisillä tiedoilla.",
            ),
            limitations=(
                "Tämä on täydellisen tiedon loppupelituloste, ei arvio siitä mitä pelaaja tiesi päätöshetkellä.",
            ),
            equivalent=tuple(
                PlayCardAction(seat=decision.action.seat, card=card)
                for card in solution.optimal_cards
            ),
            quantitative={
                "metric": "own_team_final_tricks",
                "chosen_value": chosen_value,
                "best_value": best_value,
                "difference": regret,
                "unit": "tricks",
            },
        ),
    )


def _rule_candidate(
    decision: HistoricalDecision,
    runner: LiveMatchRunner,
) -> _Candidate | None:
    if not isinstance(decision.action, PlayCardAction):
        return None
    state = decision.deal_state
    trick_index = len(state.completed_tricks)
    if trick_index >= 13:
        return None
    completed = runner.state.completed_deals[state.deal_number].public_result.completed_tricks[
        trick_index
    ]

    cheaper: list[PlayCardAction] = []
    if completed.winner == decision.action.seat:
        for alternative in decision.observation.legal_actions:
            if not isinstance(alternative, PlayCardAction):
                continue
            if alternative.card.suit is not decision.action.card.suit:
                continue
            if alternative.card.rank >= decision.action.card.rank:
                continue
            replaced = tuple(
                PlayedCard(
                    seat=play.seat,
                    card=(alternative.card if play.seat == decision.action.seat else play.card),
                )
                for play in completed.plays
            )
            if len({play.card for play in replaced}) == 4 and trick_winner(replaced) == completed.winner:
                cheaper.append(alternative)
    if cheaper:
        suggested = min(cheaper, key=lambda action: action.card.rank.value)
        return _Candidate(
            priority=700 + _late_importance(decision),
            item=_item(
                decision,
                source="Rule-based",
                confidence="objective_rule_pattern",
                source_id=RULE_SOURCE_ID,
                reason_code="cheaper_card_same_trick_winner",
                title="Halvempi kortti olisi riittänyt",
                summary=(
                    f"{card_to_code(suggested.card)} olisi voittanut saman tikin "
                    "myöhempien toteutuneiden korttien pysyessä samoina."
                ),
                recommended=suggested,
                recommendation=f"Säästä korkeampi kortti ja harkitse {card_to_code(suggested.card)}.",
                explanation=(
                    "Tulos perustuu vain toteutuneen tikin kortteihin ja lailliseen halvempaan vaihtoehtoon.",
                ),
                limitations=(
                    "Diagnoosi ei väitä, että myöhempi jako etenisi muuten muuttumattomana.",
                ),
            ),
        )

    if state.current_trick:
        partner = partner_for_seat(decision.action.seat)
        current_winner = max(
            (play for play in state.current_trick if play.card.suit is state.current_trick[0].card.suit),
            key=lambda play: play.card.rank.value,
        ).seat
        if current_winner == partner:
            extended = state.current_trick + (
                PlayedCard(seat=decision.action.seat, card=decision.action.card),
            )
            after_winner = max(
                (play for play in extended if play.card.suit is extended[0].card.suit),
                key=lambda play: play.card.rank.value,
            ).seat
            preserving: list[PlayCardAction] = []
            for alternative in decision.observation.legal_actions:
                if not isinstance(alternative, PlayCardAction):
                    continue
                hypothetical = state.current_trick + (
                    PlayedCard(seat=decision.action.seat, card=alternative.card),
                )
                winner = max(
                    (play for play in hypothetical if play.card.suit is hypothetical[0].card.suit),
                    key=lambda play: play.card.rank.value,
                ).seat
                if winner == partner:
                    preserving.append(alternative)
            if after_winner == decision.action.seat and preserving:
                suggested = min(preserving, key=lambda action: action.card.rank.value)
                return _Candidate(
                    priority=660 + _late_importance(decision),
                    item=_item(
                        decision,
                        source="Rule-based",
                        confidence="objective_rule_pattern",
                        source_id=RULE_SOURCE_ID,
                        reason_code="overtook_partner_in_current_trick",
                        title="Kortti ohitti parin",
                        summary=(
                            f"{card_to_code(decision.action.card)} ohitti parin sillä hetkellä; "
                            f"{card_to_code(suggested.card)} olisi jättänyt parin johtoon."
                        ),
                        recommended=suggested,
                        recommendation="Vertaa parin johtoasemaa ennen korkeammalla kortilla ohittamista.",
                        explanation=(
                            "Havainto kuvaa päätöshetken julkista tikkitilannetta, ei koko jaon optimaalista strategiaa.",
                        ),
                        limitations=(
                            "Myöhemmin tikkiin pelattavat kortit voivat silti muuttaa voittajan.",
                        ),
                    ),
                )
    return None


def _reference_candidate(
    decision: HistoricalDecision,
    preferred: Action,
) -> _Candidate:
    showing = isinstance(decision.action, ShowAction)
    text = (
        f"{REFERENCE_PROFILE_KEY} valitsi samasta historiallisesta pelaajahavainnosta "
        f"vaihtoehdon {_action_title(preferred)}."
    )
    return _Candidate(
        priority=(520 if showing else 400) + _late_importance(decision),
        item=_item(
            decision,
            source="Reference",
            confidence="reference_policy_only",
            source_id=REFERENCE_SOURCE_ID,
            reason_code="reference_policy_disagreement",
            title=("Näyttövertailu" if showing else "Vertailupolitiikka valitsi toisin"),
            summary=text,
            recommended=preferred,
            recommendation=f"Vertailuvaihtoehto: {_action_title(preferred)}.",
            explanation=(
                f"{REFERENCE_PROFILE_KEY} sai vain päätöshetken muodollisen pelaajahavainnon.",
            ),
            limitations=(
                f"{REFERENCE_PROFILE_KEY} on käytännön vertailupolitiikka, ei matemaattinen optimi tai todiste virheestä.",
            ),
        ),
    )


def _item(
    decision: HistoricalDecision,
    *,
    source: str,
    confidence: str,
    source_id: str,
    reason_code: str,
    title: str,
    summary: str,
    recommended: Action,
    recommendation: str,
    explanation: tuple[str, ...],
    limitations: tuple[str, ...],
    equivalent: tuple[Action, ...] = (),
    quantitative: Mapping[str, object] | None = None,
) -> dict[str, object]:
    observation = decision.observation
    state = decision.deal_state
    action_key = f"{decision.state.match_ref}:{decision.event_index}:{decision.action.seat}:{source}"
    analysis_id = "analysis:" + hashlib.sha256(action_key.encode("utf-8")).hexdigest()[:24]
    legal = [action_to_data(action) for action in observation.legal_actions]
    recommended_data = action_to_data(recommended)
    alternatives = [
        {
            "rank": 1,
            "action": recommended_data,
            "title": _action_title(recommended),
            "assessment": source,
            "reason": recommendation,
        }
    ]
    contract = None if observation.contract is None else observation.contract.value
    trick_index = None if isinstance(decision.action, ShowAction) else len(state.completed_tricks)
    return {
        "schema_version": POST_MATCH_DIAGNOSTICS_SCHEMA_VERSION,
        "analysis_id": analysis_id,
        "match_ref": decision.state.match_ref,
        "event_index": decision.event_index,
        "deal_number": state.deal_number,
        "trick_index": trick_index,
        "seat": decision.action.seat,
        "decision_kind": "SHOWING" if isinstance(decision.action, ShowAction) else "TRICK_PLAY",
        "title": title,
        "summary": summary,
        "played_action": action_to_data(decision.action),
        "recommended_action": recommended_data,
        "recommendation": recommendation,
        "alternatives": alternatives,
        "explanation": list(explanation),
        "limitations": list(limitations),
        "source": source,
        "confidence": confidence,
        "source_id": source_id,
        "reason_code": reason_code,
        "legal_actions": legal,
        "equivalent_actions": [action_to_data(action) for action in equivalent],
        "context": {
            "contract": contract,
            "player_role": _player_role(observation),
            "trick_number": None if trick_index is None else trick_index + 1,
            "current_trick": [
                {"seat": play.seat, "card": card_to_code(play.card)}
                for play in observation.current_trick
            ],
            "score": [observation.match_score.team0, observation.match_score.team1],
            "team_tricks": list(observation.team_tricks),
        },
        "quantitative": None if quantitative is None else dict(quantitative),
    }


def _player_role(observation: PlayerObservation) -> str:
    if observation.phase is EnginePhase.SHOWING:
        return "showing_player"
    if observation.contract is Contract.NOLO:
        return "nolo_player"
    if observation.declarer == observation.observing_seat:
        return "declarer"
    if observation.declarer is not None and team_for_seat(observation.declarer) is observation.team:
        return "declarer_partner"
    return "defender"


def _action_title(action: Action) -> str:
    if isinstance(action, ShowAction):
        return f"näytä {card_to_code(action.shown_card)} · {action.declared_contract.value}"
    return f"pelaa {card_to_code(action.card)}"


def _late_importance(decision: HistoricalDecision) -> int:
    if isinstance(decision.action, ShowAction):
        return 20
    return len(decision.deal_state.completed_tricks)
