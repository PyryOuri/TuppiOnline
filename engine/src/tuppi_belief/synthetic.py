"""Deterministic, labelled synthetic belief positions.

Labels are intentionally kept in this offline object only.  The public
observation returned by :meth:`SyntheticBeliefPosition.public_input` contains
no true hand, generator-policy label, stream identity, or fixture metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

from tuppi_agents import construct_agent, phase4_specifications_by_profile_key
from tuppi_engine import (
    DealState,
    EnginePhase,
    ExplicitDeal,
    PlayerObservation,
    apply_match_action,
    begin_explicit_deal,
    create_match,
    match_observation_for,
)
from tuppi_eval.serialization import content_digest
from tuppi_exact.constraints import HardConstraintModel
from tuppi_match.streams import MatchStream
from tuppi_rules import Card, MatchScore


SYNTHETIC_MANIFEST_VERSION = "tuppi.belief.synthetic_manifest.v1"


@dataclass(frozen=True, slots=True)
class SyntheticBeliefPosition:
    observation: PlayerObservation
    true_current_hands: tuple[tuple[Card, ...], ...]
    generating_profile_key: str
    position_id: str
    split: str
    stream_index: int
    deal_index: int
    phase_depth: str

    def public_input(self) -> PlayerObservation:
        return self.observation

    def to_public_data(self) -> dict[str, object]:
        return {
            "observation_schema": self.observation.schema_version,
            "phase_depth": self.phase_depth,
            "position_id": self.position_id,
            "split": self.split,
        }


def generate_synthetic_positions(
    *,
    profile_key: str,
    root_seed: str,
    stream_index: int,
    deal_indices: tuple[int, ...] = (0,),
    split: str = "development",
    initial_dealer: int = 0,
) -> tuple[SyntheticBeliefPosition, ...]:
    """Generate causal positions from a frozen homogeneous policy game."""

    specifications = phase4_specifications_by_profile_key()
    if profile_key not in specifications:
        raise ValueError(f"unknown synthetic profile {profile_key!r}")
    stream = MatchStream.build(
        root_seed=root_seed,
        stream_index=stream_index,
        initial_dealer=initial_dealer,
    )
    agents = tuple(
        construct_agent(specifications[profile_key], seat=seat) for seat in range(4)
    )
    collected: list[SyntheticBeliefPosition] = []
    for deal_index in deal_indices:
        deal = stream.deal(deal_index)
        match = create_match(
            initial_score=MatchScore(),
            initial_dealer=initial_dealer,
            match_ref=f"belief-synthetic-{stream_index}-{deal_index}",
        )
        match = begin_explicit_deal(
            match,
            ExplicitDeal(dealer=initial_dealer, hands=deal.hands),
        )
        ordinal = 0
        while match.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            actor = match.current_actor
            if actor is None or match.active_deal is None:
                raise RuntimeError("synthetic match lost its active actor")
            observation = match_observation_for(match, actor)
            active = match.active_deal
            if _keep_position(observation) and HardConstraintModel.build(observation).unknown_cards:
                depth = (
                    "showing"
                    if observation.phase is EnginePhase.SHOWING
                    else _depth_label(len(observation.completed_tricks), len(observation.current_trick))
                )
                identity = content_digest(
                    {
                        "deal_index": deal_index,
                        "depth": depth,
                        "profile_key": profile_key,
                        "root_seed": root_seed,
                        "stream_index": stream_index,
                        "step": ordinal,
                    }
                )
                collected.append(
                    SyntheticBeliefPosition(
                        observation=observation,
                        true_current_hands=tuple(active.hands),
                        generating_profile_key=profile_key,
                        position_id=identity,
                        split=split,
                        stream_index=stream_index,
                        deal_index=deal_index,
                        phase_depth=depth,
                    )
                )
            match = apply_match_action(match, agents[actor].choose_action(observation))
            ordinal += 1
    return tuple(collected)


def _keep_position(observation: PlayerObservation) -> bool:
    if observation.phase is EnginePhase.SHOWING:
        return True
    return len(observation.completed_tricks) in {0, 1, 4, 8, 12}


def _depth_label(completed: int, partial: int) -> str:
    phase = "early" if completed <= 1 else "late" if completed >= 8 else "middle"
    return f"{phase}_{completed}_trick_{partial}"
