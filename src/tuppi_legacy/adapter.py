"""Finite, all-AI adapter around the unchanged legacy game loop."""

from __future__ import annotations

import contextlib
import io
import platform
import random
from dataclasses import dataclass
from typing import Any, Sequence

from .constants import (
    ADAPTER_VERSION,
    AGENT_ID,
    ARTIFACT_ID,
    COMMON_FIDELITY_WARNINGS,
    DEAL_GENERATOR_ID,
    DEFAULT_SHOW_BANNED_RANKS,
    EMULATOR_SHA256,
    RESULT_SCHEMA_VERSION,
)
from .deals import Deal, compute_deal_set_digest, validate_deal
from .errors import ConfigurationError, LegacyExecutionError
from .legacy_loader import load_legacy_module


@dataclass(frozen=True)
class RunnerConfig:
    deal_count: int
    legacy_rng_seed: int
    rollouts: int
    scoring: str
    show_banned_ranks: tuple[int, ...] = DEFAULT_SHOW_BANNED_RANKS
    deal_source_mode: str = "programmatic"
    deal_generation_seed: int | None = None
    initial_dealer: int | None = None

    def validate(self) -> None:
        if type(self.deal_count) is not int or self.deal_count <= 0:
            raise ConfigurationError("deal count must be a positive integer")
        if type(self.legacy_rng_seed) is not int:
            raise ConfigurationError("legacy RNG seed must be an integer")
        if type(self.rollouts) is not int or self.rollouts <= 0:
            raise ConfigurationError("rollout count must be a positive integer")
        if self.scoring not in {"rising", "flat"}:
            raise ConfigurationError("scoring must be either 'rising' or 'flat'")
        if not isinstance(self.show_banned_ranks, tuple):
            raise ConfigurationError("show_banned_ranks must be a tuple")
        if len(set(self.show_banned_ranks)) != len(self.show_banned_ranks):
            raise ConfigurationError("show-banned ranks must not contain duplicates")
        for rank in self.show_banned_ranks:
            if type(rank) is not int or rank not in range(2, 15):
                raise ConfigurationError("show-banned ranks must be integers in 2..14")
        if self.deal_source_mode not in {"generated", "explicit_file", "programmatic"}:
            raise ConfigurationError(
                "deal_source_mode must be 'generated', 'explicit_file', or 'programmatic'"
            )
        if self.deal_source_mode == "generated":
            if type(self.deal_generation_seed) is not int:
                raise ConfigurationError(
                    "generated deal input requires an integer deal_generation_seed"
                )
            if type(self.initial_dealer) is not int or self.initial_dealer not in range(4):
                raise ConfigurationError(
                    "generated deal input requires initial_dealer in 0..3"
                )
        elif self.deal_generation_seed is not None or self.initial_dealer is not None:
            raise ConfigurationError(
                "deal generation seed/dealer are valid only for generated input"
            )

    def effective_dict(self, *, deal_set_digest: str) -> dict[str, Any]:
        deal_input: dict[str, Any] = {
            "mode": self.deal_source_mode,
            "materialized_deal_set_sha256": deal_set_digest,
        }
        if self.deal_source_mode == "generated":
            deal_input.update(
                {
                    "generation_algorithm": DEAL_GENERATOR_ID,
                    "generation_seed": self.deal_generation_seed,
                    "initial_dealer": self.initial_dealer,
                }
            )
        return {
            "deal_count": self.deal_count,
            "deal_input": deal_input,
            "legacy_rng_seed": self.legacy_rng_seed,
            "legacy_rng_scope": "one_shared_stream_across_all_deals_and_pimc",
            "rollouts_per_legal_move": self.rollouts,
            "scoring": self.scoring,
            "show_banned_ranks": list(self.show_banned_ranks),
            "analysis": "none",
            "runner_mode": "fixed_deal_count_all_ai",
        }


class _LegacyRandomRouter:
    """Inject complete decks while retaining one shared legacy RNG stream."""

    def __init__(self, seed: int):
        self._rng = random.Random(seed)
        self._pending_deck: list[int] | None = None
        self._injections = 0

    def begin_deal(self, deal: Deal) -> None:
        if self._pending_deck is not None:
            raise LegacyExecutionError("previous materialized deal was not consumed")
        self._pending_deck = deal.flat_deck()

    def shuffle(self, sequence: list[Any]) -> None:
        if self._pending_deck is not None and sequence == list(range(52)):
            sequence[:] = self._pending_deck
            self._pending_deck = None
            self._injections += 1
            return
        self._rng.shuffle(sequence)

    def finish_deal(self, expected_injections: int) -> None:
        if self._pending_deck is not None:
            raise LegacyExecutionError("legacy game did not consume the materialized deal")
        if self._injections != expected_injections:
            raise LegacyExecutionError(
                "unexpected number of legacy deck injections: "
                f"expected {expected_injections}, observed {self._injections}"
            )

    def seed(self, *_args: Any, **_kwargs: Any) -> None:
        raise LegacyExecutionError(
            "the adapter must construct the legacy game with seed=None"
        )


class _Recorder:
    def __init__(self, legacy: Any):
        self.legacy = legacy
        self.show_actions: list[dict[str, Any]] = []
        self.play_actions: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.show_actions.clear()
        self.play_actions.clear()

    def record_show(self, player: Any, bid: Any, banned: set[int]) -> None:
        if bid.choice not in {self.legacy.Contract.RAMI, self.legacy.Contract.NOLO}:
            raise LegacyExecutionError(
                f"legacy AI at seat {player.seat} returned invalid show choice {bid.choice!r}"
            )
        legal_show = [
            card for card in player.hand if self.legacy.card_rank(card) not in banned
        ]
        desired_red = bid.choice == self.legacy.Contract.RAMI
        matching = [
            card for card in legal_show if self.legacy.is_red(card) == desired_red
        ]
        if bid.card is None:
            if not bid.verbal:
                raise LegacyExecutionError(
                    f"legacy AI at seat {player.seat} returned no show card without a verbal bid"
                )
            if matching:
                raise LegacyExecutionError(
                    f"legacy AI at seat {player.seat} used a verbal bid despite having a legal matching card"
                )
        else:
            if bid.verbal:
                raise LegacyExecutionError(
                    f"legacy AI at seat {player.seat} marked a card bid as verbal"
                )
            if bid.card not in player.hand:
                raise LegacyExecutionError(
                    f"legacy AI at seat {player.seat} showed a card outside its hand"
                )
            if self.legacy.card_rank(bid.card) in banned:
                raise LegacyExecutionError(
                    f"legacy AI at seat {player.seat} showed a banned rank"
                )
            if self.legacy.is_red(bid.card) != desired_red:
                raise LegacyExecutionError(
                    f"legacy AI at seat {player.seat} returned a show card inconsistent with its choice"
                )
        self.show_actions.append(
            {
                # The unchanged game asks self.players in seat order; the
                # adapter installs that list as seats 0,1,2,3.
                "selection_index": player.seat,
                "seat": player.seat,
                "choice": bid.choice,
                "card": bid.card,
                "card_text": (
                    self.legacy.short_card_str(bid.card) if bid.card is not None else None
                ),
                "verbal": bool(bid.verbal),
            }
        )

    def record_play_request(self, player: Any, pub: Any, card: int) -> None:
        legal = self.legacy.legal_moves(player.hand, pub.lead_suit())
        self.play_actions.append(
            {
                "sequence_index": pub.trick_index * 4 + len(pub.current_trick),
                "trick_index": pub.trick_index,
                "position": len(pub.current_trick),
                "seat": player.seat,
                "requested_card": card,
                "requested_card_text": (
                    self.legacy.short_card_str(card)
                    if type(card) is int and card in range(52)
                    else None
                ),
                "requested_card_is_legal": card in legal,
                "executed_card": None,
                "executed_card_text": None,
                "engine_fallback_applied": None,
                "leader": pub.leader,
                "contract": pub.contract,
                "declarer": pub.declarer,
                "revealed_show_cards": dict(pub.revealed_show_cards),
            }
        )

    def record_executed_card(self, seat: int, card: int) -> None:
        pending = [
            action
            for action in self.play_actions
            if action["seat"] == seat and action["executed_card"] is None
        ]
        if len(pending) != 1:
            raise LegacyExecutionError(
                f"could not associate executed card for seat {seat} with one pending request"
            )
        action = pending[0]
        action["executed_card"] = card
        action["executed_card_text"] = self.legacy.short_card_str(card)
        action["engine_fallback_applied"] = action["requested_card"] != card


class _RecordingHand(list[int]):
    """Log only removals from an actual player's engine-owned hand."""

    def __init__(self, cards: Sequence[int], *, seat: int, recorder: _Recorder):
        super().__init__(cards)
        self._seat = seat
        self._recorder = recorder

    def remove(self, card: int) -> None:
        super().remove(card)
        self._recorder.record_executed_card(self._seat, card)


def _recording_ai_class(legacy: Any, recorder: _Recorder) -> type:
    class RecordingMonteCarloAI(legacy.MonteCarloAI):
        def set_hand(self, cards: list[int]) -> None:
            super().set_hand(cards)
            self.hand = _RecordingHand(self.hand, seat=self.seat, recorder=recorder)

        def choose_show_bid(self, dealer: int, score_state: Any, show_banned_ranks: set[int]) -> Any:
            bid = super().choose_show_bid(dealer, score_state, show_banned_ranks)
            recorder.record_show(self, bid, set(show_banned_ranks))
            return bid

        def choose_play_card(self, pub: Any, show_banned_ranks: set[int]) -> int:
            card = super().choose_play_card(pub, show_banned_ranks)
            recorder.record_play_request(self, pub, card)
            return card

    RecordingMonteCarloAI.__name__ = "RecordingMonteCarloAI"
    return RecordingMonteCarloAI


def _score_snapshot(score_state: Any) -> dict[str, Any]:
    return {
        "rising": bool(score_state.rising),
        "rising_team": score_state.rising_team,
        "scores": list(score_state.scores),
        "totals": list(score_state.totals),
    }


def _auction_summary(legacy: Any, dealer: int, actions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if len(actions) != 4 or {action["seat"] for action in actions} != set(range(4)):
        raise LegacyExecutionError("legacy game did not collect exactly one show action per seat")

    by_seat = {action["seat"]: dict(action) for action in actions}
    reveal_order = [(dealer + 1 + offset) % 4 for offset in range(4)]
    contract = legacy.Contract.NOLO
    declarer = None
    revealed_seats: list[int] = []
    for reveal_index, seat in enumerate(reveal_order):
        action = by_seat[seat]
        action["revealed"] = True
        action["reveal_index"] = reveal_index
        revealed_seats.append(seat)
        if action["choice"] == legacy.Contract.RAMI:
            contract = legacy.Contract.RAMI
            declarer = seat
            break

    for seat, action in by_seat.items():
        if seat not in revealed_seats:
            action["revealed"] = False
            action["reveal_index"] = None

    return {
        "contract": contract,
        "declarer": declarer,
        "forehand": (dealer + 1) % 4,
        "reveal_order": revealed_seats,
        "actions": [by_seat[seat] for seat in range(4)],
    }


def _play_summary(legacy: Any, actions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    actions = sorted(actions, key=lambda action: action["sequence_index"])
    if len(actions) != 52:
        raise LegacyExecutionError(
            f"legacy game produced {len(actions)} recorded plays; expected 52"
        )

    contracts = {action["contract"] for action in actions}
    declarers = {action["declarer"] for action in actions}
    revealed_snapshots = {
        tuple(sorted(action["revealed_show_cards"].items())) for action in actions
    }
    if len(contracts) != 1 or len(declarers) != 1 or len(revealed_snapshots) != 1:
        raise LegacyExecutionError(
            "contract, declarer, or revealed show cards changed during a legacy deal"
        )

    transcript = [
        {
            "sequence_index": action["sequence_index"],
            "trick_index": action["trick_index"],
            "position": action["position"],
            "seat": action["seat"],
            "card": action["executed_card"],
            "card_text": action["executed_card_text"],
            "requested_card": action["requested_card"],
            "requested_card_text": action["requested_card_text"],
            "requested_card_is_legal": action["requested_card_is_legal"],
            "engine_fallback_applied": action["engine_fallback_applied"],
        }
        for action in actions
    ]
    tricks: list[dict[str, Any]] = []
    tricks_by_player = [0, 0, 0, 0]
    for trick_index in range(13):
        trick_actions = [
            action for action in actions if action["trick_index"] == trick_index
        ]
        if len(trick_actions) != 4:
            raise LegacyExecutionError(
                f"legacy trick {trick_index} has {len(trick_actions)} recorded cards"
            )
        if [action["position"] for action in trick_actions] != [0, 1, 2, 3]:
            raise LegacyExecutionError(
                f"legacy trick {trick_index} has invalid play positions"
            )
        if any(action["executed_card"] is None for action in trick_actions):
            raise LegacyExecutionError(
                f"legacy trick {trick_index} has an unrecorded engine action"
            )
        pairs = [
            (action["seat"], action["executed_card"]) for action in trick_actions
        ]
        winner = legacy.trick_winner(pairs)
        tricks_by_player[winner] += 1
        tricks.append(
            {
                "trick_index": trick_index,
                "leader": trick_actions[0]["leader"],
                "plays": [
                    {
                        "seat": action["seat"],
                        "card": action["executed_card"],
                        "card_text": action["executed_card_text"],
                    }
                    for action in trick_actions
                ],
                "winner_seat": winner,
                "winner_team": legacy.team_of(winner),
            }
        )

    tricks_by_team = [
        tricks_by_player[0] + tricks_by_player[2],
        tricks_by_player[1] + tricks_by_player[3],
    ]
    return {
        "observed_contract": next(iter(contracts)),
        "observed_declarer": next(iter(declarers)),
        "observed_revealed_show_cards": dict(next(iter(revealed_snapshots))),
        "card_play_transcript": transcript,
        "tricks": tricks,
        "tricks_by_player": tricks_by_player,
        "tricks_by_team": tricks_by_team,
    }


def execute_legacy_deals(config: RunnerConfig, deals: Sequence[Deal]) -> list[dict[str, Any]]:
    config.validate()
    if len(deals) != config.deal_count:
        raise ConfigurationError(
            f"configuration requests {config.deal_count} deals but {len(deals)} were supplied"
        )
    for deal in deals:
        validate_deal(deal)
    deal_set_digest = compute_deal_set_digest(deals)

    legacy = load_legacy_module()
    exact_bans = set(config.show_banned_ranks)
    constructor_bans = exact_bans if exact_bans else set(DEFAULT_SHOW_BANNED_RANKS)
    game = legacy.TuppiGame(
        human_seat=0,
        rollouts=config.rollouts,
        rising_scoring=config.scoring == "rising",
        seed=None,
        show_banned_ranks=constructor_bans,
        analysis_level="none",
        analysis_move_rollouts=None,
        analysis_topn=1,
    )
    # The frozen constructor uses ``value or default``. Assigning the validated
    # public attribute before any deal is the only faithful way to represent an
    # explicitly empty set without modifying Archive/.
    game.show_banned_ranks = set(exact_bans)
    if game.show_banned_ranks != exact_bans:
        raise LegacyExecutionError(
            "legacy game could not preserve the exact configured show-ban set"
        )

    # Keep one recorder per seat. No object reachable through one recording
    # wrapper contains another player's private show selection or hand.
    recorders = [_Recorder(legacy) for _ in range(4)]
    game.players = []
    for seat, recorder in enumerate(recorders):
        recording_ai = _recording_ai_class(legacy, recorder)
        game.players.append(
            recording_ai(
                seat, name=legacy.dealer_name(seat), rollouts=config.rollouts
            )
        )

    router = _LegacyRandomRouter(config.legacy_rng_seed)
    original_random = legacy.random
    records: list[dict[str, Any]] = []
    try:
        # Rebind only the frozen module's global name. Replacing
        # ``random.shuffle`` itself would mutate the process-wide stdlib module.
        legacy.random = router
        for deal_index, deal in enumerate(deals):
            for recorder in recorders:
                recorder.reset()
            game.dealer = deal.dealer
            score_before = _score_snapshot(game.score_state)
            router.begin_deal(deal)
            with contextlib.redirect_stdout(io.StringIO()):
                game.play_one_hand()
            router.finish_deal(deal_index + 1)

            show_actions = [
                action for recorder in recorders for action in recorder.show_actions
            ]
            play_actions = [
                action for recorder in recorders for action in recorder.play_actions
            ]
            auction = _auction_summary(legacy, deal.dealer, show_actions)
            play = _play_summary(legacy, play_actions)
            if (
                play["observed_contract"] != auction["contract"]
                or play["observed_declarer"] != auction["declarer"]
            ):
                raise LegacyExecutionError(
                    "recorded auction outcome disagrees with the PublicState observed by players"
                )
            expected_revealed = {
                action["seat"]: action["card"]
                for action in auction["actions"]
                if action["revealed"] and action["card"] is not None
            }
            if play["observed_revealed_show_cards"] != expected_revealed:
                raise LegacyExecutionError(
                    "recorded reveal actions disagree with revealed_show_cards in PublicState"
                )

            tricks_by_team = play["tricks_by_team"]
            deal_winner, deal_points = legacy.score_deal(
                auction["contract"],
                auction["declarer"],
                tricks_by_team[0],
                tricks_by_team[1],
            )
            warnings = list(COMMON_FIDELITY_WARNINGS)
            if not exact_bans:
                warnings.append(
                    "An explicit empty show-ban set was assigned after construction to bypass the frozen constructor's legacy default substitution."
                )

            records.append(
                {
                    "schema_version": RESULT_SCHEMA_VERSION,
                    "adapter_version": ADAPTER_VERSION,
                    "artifact_id": ARTIFACT_ID,
                    "ruleset_id": ARTIFACT_ID,
                    "emulator_sha256": EMULATOR_SHA256,
                    "python_version": platform.python_version(),
                    "effective_configuration": {
                        **config.effective_dict(deal_set_digest=deal_set_digest),
                        "deal_index": deal_index,
                    },
                    "deal_id": deal.deal_id,
                    "initial_deal": deal.to_dict(),
                    "dealer": deal.dealer,
                    "agents": [
                        {
                            "seat": seat,
                            "identity": AGENT_ID,
                            "rollouts_per_legal_move": config.rollouts,
                        }
                        for seat in range(4)
                    ],
                    "auction": auction,
                    "contract": auction["contract"],
                    "declarer": auction["declarer"],
                    "card_play_transcript": play["card_play_transcript"],
                    "tricks": play["tricks"],
                    "terminal": {
                        "tricks_by_player": play["tricks_by_player"],
                        "tricks_by_team": tricks_by_team,
                        "deal_winner_team": deal_winner,
                        "deal_points": deal_points,
                        "legacy_score_before": score_before,
                        "legacy_score_after": _score_snapshot(game.score_state),
                    },
                    "execution": {
                        "status": "ok",
                        "legacy_stdout_parsed": False,
                        "stdin_required": False,
                        "gui_required": False,
                        "network_required": False,
                    },
                    "fidelity_warnings": warnings,
                }
            )
    except LegacyExecutionError:
        raise
    except Exception as exc:
        raise LegacyExecutionError(
            f"legacy execution failed with {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        legacy.random = original_random

    return records
