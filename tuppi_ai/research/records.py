"""Typed research records, truth separation and split lineage (C0.02; A10, V08).

Policy-facing records (`DecisionCase`) carry only an actor's legal
observation (the engine wire form), the ordered legal actions and an optional
reference to the actor's own permitted policy state. Evaluator truth
(`OfflineTruth`: every original hand and the full action history) lives in a
separate `TruthStore`, which the runner and oracles read and which no
policy-facing record references.

Splits are keyed by the original parent deal: every observation, world,
rotation or completion derived from one parent stays in that parent's split.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SPLITS = ("DEV", "FIT", "PLAN", "SCREEN", "CONFIRM")
RECORD_SCHEMA = "tuppi.research.records.v1"


class SplitLeakError(ValueError):
    """A parent deal (or a derivative) was assigned to two splits."""


class TruthLeakError(ValueError):
    """A policy-facing record contains evaluator-only information."""


def parent_deal_id(namespace: str, index: int) -> str:
    """Stable id of an original base deal in a named namespace."""
    return "deal:" + hashlib.sha256(f"tuppi.research.deal.v1|{namespace}|{index}".encode()).hexdigest()[:32]


@dataclass(frozen=True)
class DecisionCase:
    """One actor decision as the policy may see it. No truth reference."""

    case_id: str
    cluster_id: str
    split: str
    observation: dict
    ordered_action_ids: tuple[int, ...]
    policy_snapshot_ref: str | None = None
    population: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.split not in SPLITS:
            raise ValueError(f"unknown split {self.split}")
        forbidden = {"hands", "initial_hands", "truth", "world", "worlds", "layout"}
        if forbidden & set(self.population):
            raise TruthLeakError(f"population metadata carries evaluator fields {forbidden & set(self.population)}")

    def policy_observation(self):
        """The typed PlayerObservation a policy receives (via the strict inverse)."""
        from .observation import observation_from_data

        return observation_from_data(self.observation)

    def to_data(self) -> dict:
        return {"schema": RECORD_SCHEMA, "kind": "DecisionCase", **asdict(self),
                "ordered_action_ids": list(self.ordered_action_ids)}

    @classmethod
    def from_data(cls, data: dict) -> "DecisionCase":
        if data.get("kind") != "DecisionCase" or data.get("schema") != RECORD_SCHEMA:
            raise ValueError("not a DecisionCase record")
        return cls(data["case_id"], data["cluster_id"], data["split"], data["observation"],
                   tuple(data["ordered_action_ids"]), data.get("policy_snapshot_ref"), data.get("population", {}))


@dataclass(frozen=True)
class OfflineTruth:
    """Evaluator-only facts of one original deal."""

    cluster_id: str
    ruleset: str
    dealer: int
    starting_score: tuple[int, int]
    initial_hands: tuple[tuple[str, ...], ...]
    action_history: tuple[dict, ...]
    notes: dict = field(default_factory=dict)

    def to_data(self) -> dict:
        return {"schema": RECORD_SCHEMA, "kind": "OfflineTruth", **asdict(self)}

    @classmethod
    def from_data(cls, data: dict) -> "OfflineTruth":
        if data.get("kind") != "OfflineTruth":
            raise ValueError("not an OfflineTruth record")
        return cls(data["cluster_id"], data["ruleset"], data["dealer"], tuple(data["starting_score"]),
                   tuple(tuple(h) for h in data["initial_hands"]), tuple(data["action_history"]),
                   data.get("notes", {}))


class TruthStore:
    """Evaluator-private truth, stored apart from every policy-facing record."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def path(self, cluster_id: str) -> Path:
        return self.root / (cluster_id.replace(":", "_") + ".truth.json")

    def put(self, truth: OfflineTruth) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.path(truth.cluster_id)
        p.write_text(json.dumps(truth.to_data(), indent=1, sort_keys=True))
        return p

    def get(self, cluster_id: str) -> OfflineTruth:
        return OfflineTruth.from_data(json.loads(self.path(cluster_id).read_text()))


def visible_card_codes(observation: dict) -> set[str]:
    """Every card an observation legally shows its actor."""
    cards = set(observation["own_hand"])
    for trick in observation["completed_tricks"]:
        cards.update(p["card"] for p in trick["plays"])
    cards.update(p["card"] for p in observation["current_trick"])
    cards.update(s["shown_card"] for s in observation["show_actions"])
    sooli = observation.get("sooli") or {}
    cards.update(c for c in (sooli.get("given_card"), sooli.get("returned_card")) if c)
    for a in observation["legal_actions"]:
        cards.update(a[k] for k in ("card", "shown_card") if k in a)
    return cards


def _string_leaves(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _string_leaves(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _string_leaves(v)


def check_no_truth(case: DecisionCase, truth: OfflineTruth) -> None:
    """A10: a policy-facing case holds no hidden card of another seat.

    Every card-code token found in ANY string of the serialised case (not only
    whole card fields) must be visible to the actor, and the ordered action ids
    must be exactly the observation's own legal actions.
    """
    import re

    from tuppi_engine import action_from_data

    from ..bridge import action_id

    seat = case.observation["observing_seat"]
    visible = visible_card_codes(case.observation)
    hidden = {c for s, hand in enumerate(truth.initial_hands) if s != seat for c in hand} - visible
    token = re.compile(r"(?<![0-9A-Za-z])([2-9TJQKA][HDCS])(?![0-9A-Za-z])")
    found = {m for text in _string_leaves(case.to_data()) for m in token.findall(text)}
    leaked = sorted(found & hidden)
    if leaked:
        raise TruthLeakError(f"case {case.case_id} contains hidden cards {leaked}")
    legal = tuple(action_id(action_from_data(a)) for a in case.observation["legal_actions"])
    if tuple(case.ordered_action_ids) != legal:
        raise TruthLeakError(f"case {case.case_id}: ordered actions are not the observation's legal actions")
    # free-form fields must not smuggle hands as integer bit masks (any card set needs > 8 bits)
    for name, value in (("population", case.population), ("policy_snapshot_ref", case.policy_snapshot_ref)):
        big = [v for v in _int_leaves(value) if abs(v) > 255]
        if big:
            raise TruthLeakError(f"case {case.case_id}: {name} holds integers that could encode card sets: {big[:3]}")


def _int_leaves(value):
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _int_leaves(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _int_leaves(v)


class SplitRegistry:
    """Assigns parent deals to splits and rejects any overlap (V08)."""

    def __init__(self):
        self._split: dict[str, str] = {}

    def assign(self, parent_id: str, split: str) -> None:
        if split not in SPLITS:
            raise ValueError(f"unknown split {split}")
        prior = self._split.setdefault(parent_id, split)
        if prior != split:
            raise SplitLeakError(f"{parent_id} already in {prior}, not {split}")

    def split_of(self, parent_id: str) -> str:
        return self._split[parent_id]

    def check_record(self, parent_id: str, split: str) -> None:
        """A derived record (observation, world, rotation) must stay in its parent's split."""
        if self._split.get(parent_id) != split:
            raise SplitLeakError(f"record of {parent_id} labelled {split}, parent is in {self._split.get(parent_id)}")

    @staticmethod
    def check_disjoint(splits: dict[str, list[str]]) -> None:
        seen: dict[str, str] = {}
        for split, parents in splits.items():
            for p in parents:
                if p in seen and seen[p] != split:
                    raise SplitLeakError(f"{p} is in both {seen[p]} and {split}")
                seen[p] = split


@dataclass(frozen=True)
class WorldBatch:
    """Evaluator-only root worlds for one case, with their law and seed trace."""

    case_id: str
    law_id: str
    worlds: tuple[dict, ...]          # tcdeal_to_data records
    weights: tuple[float, ...] | None  # None = equal weights
    stream: dict                      # namespace, labels, rng_before, rng_after
    independence: str = "iid pseudo-random draws with replacement (SplitMix64); layouts may repeat"


@dataclass(frozen=True)
class DealTransition:
    """One completed (or failed) deal inside a runner arm (IMPLEMENTATION_SPEC.md 2.4)."""

    cluster_id: str
    arm: str
    rotation: int
    assignment: int
    dealer: int
    source_score: tuple[int, int]
    ruleset: str
    policy_ids: tuple[str, ...]
    snapshot_ids: tuple[str, ...]
    lifecycle: str
    terminal_type: str | None
    contract: str | None
    declarer: int | None
    soolaaja: int | None
    winner_team: int | None
    points: int | None
    team_tricks: tuple[int, int] | None
    next_score: tuple[int, int] | None
    next_dealer: int | None
    match_terminal: bool | None
    candidate_team: int | None
    candidate_value: float | None
    cpu_s: float
    wall_s: float
    decision_ms: tuple[float, ...]
    failed: bool = False
    failure: str | None = None
    fallbacks: int = 0
    rng_scheme: str = ""

    def to_data(self) -> dict:
        return asdict(self)
