"""Stream-separated imitation data generation and privacy-safe manifests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from tuppi_engine import (
    CompletedTrick,
    EnginePhase,
    PlayerObservation,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_engine.serialization import action_from_data, action_to_data, observation_to_data
from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_match.streams import MatchStream
from tuppi_rules import Contract, MatchScore, PlayedCard, ShowAction as RulesShowAction, Team, card_from_code

from .encoding import encode_observation
from .errors import LearningConfigurationError


DATASET_SCHEMA_VERSION = "tuppi.learning.imitation_dataset.v1"
MANIFEST_SCHEMA_VERSION = "tuppi.learning.dataset_manifest.v1"
PHASE6_DATASET_VERSION = "phase6_partner_aware_imitation_v1"


@dataclass(frozen=True, slots=True)
class ImitationExample:
    """One public observation and its frozen-policy action label."""

    observation: object
    target_action: object
    split: str
    stream_id: str
    example_index: int

    def __post_init__(self) -> None:
        from tuppi_engine import PlayCardAction, PlayerObservation, ShowAction

        if not isinstance(self.observation, PlayerObservation):
            raise LearningConfigurationError("imitation examples require PlayerObservation")
        if not isinstance(self.target_action, (PlayCardAction, ShowAction)):
            raise LearningConfigurationError("imitation labels require engine actions")
        if self.target_action not in self.observation.legal_actions:
            raise LearningConfigurationError("imitation label must be legal for the observation")
        if self.split not in {"train", "validation", "heldout"}:
            raise LearningConfigurationError("unknown imitation split")
        if not self.stream_id or type(self.example_index) is not int or self.example_index < 0:
            raise LearningConfigurationError("imitation example identity is invalid")

    @property
    def target_index(self) -> int:
        return self.observation.legal_actions.index(self.target_action)

    @property
    def phase(self) -> str:
        return self.observation.phase.value

    @property
    def contract_label(self) -> str:
        if self.observation.contract is not None:
            return self.observation.contract.value
        if hasattr(self.target_action, "declared_contract"):
            return self.target_action.declared_contract.value
        return "unknown"

    def to_data(self) -> dict[str, object]:
        return {
            "example_index": self.example_index,
            "observation": observation_to_data(self.observation),
            "schema_version": DATASET_SCHEMA_VERSION,
            "split": self.split,
            "stream_id": self.stream_id,
            "target_action": action_to_data(self.target_action),
        }


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_id: str
    dataset_version: str
    target_agent_id: str
    root_seed: int | str
    split_streams: dict[str, tuple[str, ...]]
    split_counts: dict[str, int]
    profile_schedule: tuple[tuple[str, str, str, str], ...]
    score_schedule: tuple[tuple[int, int], ...]
    initial_dealer_schedule: str
    safety_cap: int = 20
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            raise LearningConfigurationError("unsupported dataset manifest schema")
        if self.dataset_version != PHASE6_DATASET_VERSION:
            raise LearningConfigurationError("unsupported Phase 6 dataset version")
        if self.initial_dealer_schedule != "stream_index_mod_4_v1":
            raise LearningConfigurationError("unsupported initial dealer schedule")
        if set(self.split_streams) != {"train", "validation", "heldout"}:
            raise LearningConfigurationError("dataset manifest must contain all splits")
        if set(self.split_counts) != set(self.split_streams):
            raise LearningConfigurationError("dataset count keys disagree with streams")
        if any(type(value) is not int or value < 0 for value in self.split_counts.values()):
            raise LearningConfigurationError("dataset split counts must be nonnegative integers")
        stream_ids: list[str] = []
        for split, values in self.split_streams.items():
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value for value in values
            ):
                raise LearningConfigurationError(f"dataset {split} streams must be nonempty strings")
            if len(values) != len(set(values)):
                raise LearningConfigurationError(f"dataset {split} contains duplicate streams")
            stream_ids.extend(values)
        if len(stream_ids) != len(set(stream_ids)):
            raise LearningConfigurationError("dataset streams must be disjoint across splits")
        if not self.profile_schedule or any(
            len(row) != 4 or any(not isinstance(value, str) or not value for value in row)
            for row in self.profile_schedule
        ):
            raise LearningConfigurationError("dataset profile schedule is invalid")
        if not self.score_schedule or any(
            len(row) != 2 or any(type(value) is not int or value < 0 for value in row)
            for row in self.score_schedule
        ):
            raise LearningConfigurationError("dataset score schedule is invalid")
        if type(self.safety_cap) is not int or self.safety_cap <= 0:
            raise LearningConfigurationError("dataset safety_cap must be positive")
        if not (
            isinstance(self.target_agent_id, str)
            and self.target_agent_id.startswith("agent:sha256:")
            and len(self.target_agent_id) == len("agent:sha256:") + 64
            and all(
                character in "0123456789abcdef"
                for character in self.target_agent_id.removeprefix("agent:sha256:")
            )
        ):
            raise LearningConfigurationError("dataset target agent identity is not canonical")
        expected_id = _dataset_digest(
            {
                "dataset_version": self.dataset_version,
                "initial_dealer_schedule": self.initial_dealer_schedule,
                "profile_schedule": [list(item) for item in self.profile_schedule],
                "root_seed": self.root_seed,
                "safety_cap": self.safety_cap,
                "score_schedule": [list(item) for item in self.score_schedule],
                "split_counts": self.split_counts,
                "split_streams": self.split_streams,
                "target_agent_id": self.target_agent_id,
            }
        )
        if self.dataset_id != expected_id:
            raise LearningConfigurationError("dataset_id disagrees with manifest content")

    def to_data(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "initial_dealer_schedule": self.initial_dealer_schedule,
            "profile_schedule": [list(item) for item in self.profile_schedule],
            "root_seed": self.root_seed,
            "safety_cap": self.safety_cap,
            "schema_version": self.schema_version,
            "score_schedule": [list(item) for item in self.score_schedule],
            "split_counts": self.split_counts,
            "split_streams": self.split_streams,
            "target_agent_id": self.target_agent_id,
        }


DEFAULT_PROFILE_SCHEDULE: tuple[tuple[str, str, str, str], ...] = (
    ("partner_aware_v1", "partner_aware_v1", "partner_aware_v1", "partner_aware_v1"),
    ("reactive_contract_v1", "public_counting_v1", "partner_aware_v1", "public_counting_v1"),
    ("public_counting_v1", "partner_aware_v1", "reactive_contract_v1", "partner_aware_v1"),
    ("partner_aware_v1", "reactive_contract_v1", "public_counting_v1", "reactive_contract_v1"),
)
DEFAULT_SCORE_SCHEDULE: tuple[tuple[int, int], ...] = ((0, 0), (24, 0), (0, 24), (40, 0), (0, 40))


def _dataset_digest(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "dataset:sha256:" + hashlib.sha256(text).hexdigest()


def _build_agents(profile_keys: tuple[str, str, str, str]):
    specifications = phase4_specifications_by_profile_key()
    return tuple(
        construct_agent(specifications[key], seat=seat)
        for seat, key in enumerate(profile_keys)
    )


def generate_imitation_examples(
    *,
    root_seed: int | str,
    split: str,
    stream_indices: Iterable[int],
    max_examples: int | None = None,
    profile_schedule: tuple[tuple[str, str, str, str], ...] = DEFAULT_PROFILE_SCHEDULE,
    score_schedule: tuple[tuple[int, int], ...] = DEFAULT_SCORE_SCHEDULE,
    safety_cap: int = 512,
) -> tuple[ImitationExample, ...]:
    """Generate public labelled observations from frozen-policy crossplay.

    Stream IDs, not individual examples, define split membership.  No private
    hands or terminal labels are retained in the returned examples.
    """

    if split not in {"train", "validation", "heldout"}:
        raise LearningConfigurationError("split must be train, validation, or heldout")
    indices = tuple(stream_indices)
    if any(type(index) is not int or index < 0 for index in indices):
        raise LearningConfigurationError("stream_indices must be nonnegative integers")
    if not indices or len(indices) != len(set(indices)):
        raise LearningConfigurationError("stream_indices must be nonempty and unique")
    if not profile_schedule or not score_schedule:
        raise LearningConfigurationError("dataset schedules must not be empty")
    if type(safety_cap) is not int or safety_cap <= 0:
        raise LearningConfigurationError("safety_cap must be positive")
    if max_examples is not None and (type(max_examples) is not int or max_examples <= 0):
        raise LearningConfigurationError("max_examples must be positive when supplied")
    target_spec = phase4_specifications_by_profile_key()["partner_aware_v1"]
    examples: list[ImitationExample] = []
    for ordinal, stream_index in enumerate(indices):
        stream = MatchStream.build(
            root_seed=root_seed,
            stream_index=stream_index,
            initial_dealer=stream_index % 4,
        )
        profile_keys = profile_schedule[stream_index % len(profile_schedule)]
        agents = _build_agents(profile_keys)
        target_agents = tuple(
            construct_agent(target_spec, seat=seat) for seat in range(4)
        )
        score = score_schedule[stream_index % len(score_schedule)]
        state = create_match(
            initial_score=MatchScore(*score),
            initial_dealer=stream.initial_dealer,
            match_ref=f"learn-{split[:2]}-{ordinal:06d}",
        )
        deal_index = 0
        while not state.terminal and deal_index < safety_cap:
            if state.phase in (EnginePhase.AWAITING_DEAL, EnginePhase.DEAL_COMPLETE):
                deal = stream.deal(deal_index)
                state = begin_explicit_deal(state, deal.explicit_deal(state.dealer))
                deal_index += 1
                continue
            actor = state.current_actor
            if actor is None:  # pragma: no cover - authoritative invariant
                raise LearningConfigurationError("active training state has no actor")
            observation = match_observation_for(state, actor)
            label = target_agents[actor].choose_action(observation)
            examples.append(
                ImitationExample(
                    observation=observation,
                    target_action=label,
                    split=split,
                    stream_id=stream.stream_id,
                    example_index=len(examples),
                )
            )
            state = apply_match_action(state, agents[actor].choose_action(observation))
            if max_examples is not None and len(examples) >= max_examples:
                return tuple(examples)
    return tuple(examples)


def build_dataset_manifest(
    *,
    root_seed: int | str,
    target_agent_id: str,
    split_streams: dict[str, tuple[str, ...]],
    split_counts: dict[str, int],
    profile_schedule: tuple[tuple[str, str, str, str], ...] = DEFAULT_PROFILE_SCHEDULE,
    score_schedule: tuple[tuple[int, int], ...] = DEFAULT_SCORE_SCHEDULE,
    safety_cap: int = 20,
) -> DatasetManifest:
    normalized_streams = {
        key: tuple(values) for key, values in split_streams.items()
    }
    normalized_counts = dict(split_counts)
    normalized_profiles = tuple(tuple(row) for row in profile_schedule)
    normalized_scores = tuple(tuple(row) for row in score_schedule)
    payload = {
        "dataset_version": PHASE6_DATASET_VERSION,
        "initial_dealer_schedule": "stream_index_mod_4_v1",
        "profile_schedule": [list(item) for item in normalized_profiles],
        "root_seed": root_seed,
        "safety_cap": safety_cap,
        "score_schedule": [list(item) for item in normalized_scores],
        "split_counts": normalized_counts,
        "split_streams": normalized_streams,
        "target_agent_id": target_agent_id,
    }
    return DatasetManifest(
        dataset_id=_dataset_digest(payload),
        dataset_version=PHASE6_DATASET_VERSION,
        target_agent_id=target_agent_id,
        root_seed=root_seed,
        split_streams=normalized_streams,
        split_counts=normalized_counts,
        profile_schedule=normalized_profiles,
        score_schedule=normalized_scores,
        initial_dealer_schedule="stream_index_mod_4_v1",
        safety_cap=safety_cap,
    )


def write_examples_jsonl(path: str | Path, examples: Iterable[ImitationExample]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8") as handle:
        for example in examples:
            handle.write(json.dumps(example.to_data(), sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def write_manifest(path: str | Path, manifest: DatasetManifest) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest.to_data(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def observation_from_data(value: object) -> PlayerObservation:
    """Read a public observation record without accepting private state."""

    if not isinstance(value, dict):
        raise LearningConfigurationError("observation record must be an object")
    try:
        own_hand = tuple(card_from_code(item) for item in value["own_hand"])
        show_values = []
        for item in value["show_actions"]:
            # ``PlayerObservation`` carries historical show actions for all
            # seats, while the observer's current hand is not the historical
            # 13-card hand of each other seat.  The engine serializer already
            # carries the derived verbal flag, so restore this immutable public
            # value without trying to validate it against a private hand.
            show = object.__new__(RulesShowAction)
            object.__setattr__(show, "seat", item["seat"])
            object.__setattr__(show, "shown_card", card_from_code(item["shown_card"]))
            object.__setattr__(show, "declared_contract", Contract(item["declared_contract"]))
            object.__setattr__(show, "verbal_required", item["verbal_required"])
            show_values.append(show)
        show_actions = tuple(show_values)
        completed = tuple(
            CompletedTrick(
                trick_index=item["trick_index"],
                leader=item["leader"],
                plays=tuple(
                    PlayedCard(seat=play["seat"], card=card_from_code(play["card"]))
                    for play in item["plays"]
                ),
                winner=item["winner"],
            )
            for item in value["completed_tricks"]
        )
        current = tuple(
            PlayedCard(seat=item["seat"], card=card_from_code(item["card"]))
            for item in value["current_trick"]
        )
        legal_actions = tuple(action_from_data(item) for item in value["legal_actions"])
        contract = None if value["contract"] is None else Contract(value["contract"])
        observation = PlayerObservation(
            match_ref=value["match_ref"],
            deal_ref=value["deal_ref"],
            observing_seat=value["observing_seat"],
            team=Team(value["team"]),
            partner_seat=value["partner_seat"],
            dealer=value["dealer"],
            forehand=value["forehand"],
            phase=EnginePhase(value["phase"]),
            current_actor=value["current_actor"],
            own_hand=own_hand,
            show_actions=show_actions,
            publicly_shown_cards=tuple(
                (item["seat"], card_from_code(item["card"]))
                for item in value["publicly_shown_cards"]
            ),
            contract=contract,
            declarer=value["declarer"],
            first_leader=value["first_leader"],
            completed_tricks=completed,
            current_trick=current,
            team_tricks=tuple(value["team_tricks"]),
            match_score=MatchScore(*value["match_score"]),
            legal_actions=legal_actions,
            deal_terminal=value["deal_terminal"],
            match_terminal=value["match_terminal"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LearningConfigurationError("invalid public observation record") from exc
    return observation


def read_examples_jsonl(path: str | Path) -> tuple[ImitationExample, ...]:
    target = Path(path)
    examples: list[ImitationExample] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if item.get("schema_version") != DATASET_SCHEMA_VERSION:
                    raise LearningConfigurationError("unsupported imitation example schema")
                examples.append(
                    ImitationExample(
                        observation=observation_from_data(item["observation"]),
                        target_action=action_from_data(item["target_action"]),
                        split=item["split"],
                        stream_id=item["stream_id"],
                        example_index=item["example_index"],
                    )
                )
            except (ValueError, TypeError, KeyError) as exc:
                raise LearningConfigurationError(
                    f"invalid imitation example at line {line_number + 1}"
                ) from exc
    return tuple(examples)
