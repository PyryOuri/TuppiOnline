"""Declared research candidates: policies under test, kept out of production lineage.

Why this module exists. The evaluator constructs a seat's runtime object from an
``AgentSpecification``'s ``implementation_reference``, and it only knows the
references it is written to know. Phase 4 profiles and the improved policies are
each declared in a registry the factory reads. Anything else - a candidate
somebody wants to *test* - had no construction path at all, so five of the six
hypothesis families in the charter were blocked on a missing dispatch rather than
on any scientific question.

This registry supplies that path, with three deliberate boundaries:

* **Separate from production lineage.** ``improved_registry`` records what the
  product's policies *are*; this records what is being *tried*. Mixing them would
  let a candidate acquire a production identity by being evaluated, and every
  Phase 4/5/6 result is quoted against those identities.
* **Identity before behaviour.** A candidate declares its base policy and its
  override as data, and its ``agent_id`` is a content address over both. Change a
  parameter and it is a different candidate; reword a description and it is not.
* **Observation-only overrides.** An override sees the acting seat's
  ``PlayerObservation`` and nothing else, and may return only a member of
  ``observation.legal_actions``. It cannot reach private state, and it cannot
  invent an action the engine would refuse.

The two candidates declared here are **instrument controls, not proposals.**
Neither is a strategy suggestion and neither should ever be promoted:
``research_noop_v1`` exists to prove the new path changes nothing, and
``research_legal_shift_v1`` exists to prove the pipeline can detect a candidate
that genuinely differs. It is expected to play worse.
"""

from __future__ import annotations

from dataclasses import dataclass
from tuppi_engine import Agent
from tuppi_eval.identities import (
    AgentSpecification,
    DeterminismClass,
    SeedPolicy,
)

from .errors import AgentConstructionError, AgentsValidationError
from .research_overrides import OVERRIDE_IMPLEMENTATIONS

RESEARCH_CANDIDATE_SCHEMA_VERSION = "tuppi.agents.research_candidate.v1"

#: Reference prefix. Kept under ``tuppi_agents`` because these are policies and
#: the factory owns policy construction; the evaluator needs no change to route
#: them, and so stays ignorant of candidates.
REFERENCE_PREFIX = "tuppi_agents.research_candidates:"


@dataclass(frozen=True, slots=True)
class CandidateOverride:
    """The declared behavioural difference, as identity-bearing data."""

    override_id: str
    #: Ordered so identity is stable; values must be JSON scalars.
    parameters: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.override_id, str) or not self.override_id:
            raise AgentsValidationError("an override requires a nonempty id")
        if type(self.parameters) is not tuple:
            raise AgentsValidationError("override parameters must be a tuple")
        seen = set()
        for item in self.parameters:
            if type(item) is not tuple or len(item) != 2:
                raise AgentsValidationError("each parameter must be a (name, value) pair")
            name, value = item
            if not isinstance(name, str) or not name:
                raise AgentsValidationError("parameter names must be nonempty strings")
            if name in seen:
                raise AgentsValidationError(f"duplicate parameter {name!r}")
            seen.add(name)
            if not isinstance(value, (str, int, float, bool)) or isinstance(value, complex):
                raise AgentsValidationError(
                    f"parameter {name!r} must be a JSON scalar for stable identity"
                )
        if tuple(sorted(self.parameters)) != self.parameters:
            raise AgentsValidationError("override parameters must be sorted by name")

    def to_data(self) -> dict[str, object]:
        return {
            "override_id": self.override_id,
            "parameters": {name: value for name, value in self.parameters},
        }


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    """One candidate under test: a declared base plus a declared override."""

    candidate_key: str
    base_profile_key: str
    override: CandidateOverride
    #: True for a control whose purpose is to check the instrument, not to win.
    is_calibration_control: bool
    description: str

    def __post_init__(self) -> None:
        for name in ("candidate_key", "base_profile_key", "description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise AgentsValidationError(f"{name} must be a nonempty string")
        if not isinstance(self.override, CandidateOverride):
            raise AgentsValidationError("a candidate requires a CandidateOverride")
        if type(self.is_calibration_control) is not bool:
            raise AgentsValidationError("is_calibration_control must be a boolean")

    @property
    def implementation_reference(self) -> str:
        return f"{REFERENCE_PREFIX}{self.candidate_key}"


_NOOP = CandidateOverride(override_id="tuppi.research.noop.v1", parameters=())

_LEGAL_SHIFT = CandidateOverride(
    override_id="tuppi.research.legal_index_shift.v1",
    parameters=(("phase", "TRICK_PLAY"), ("shift", 1)),
)


_CANDIDATES: tuple[ResearchCandidate, ...] = (
    ResearchCandidate(
        candidate_key="research_noop_v1",
        base_profile_key="partner_aware_lead_v2",
        override=_NOOP,
        is_calibration_control=True,
        description=(
            "The imported production incumbent behind a pass-through wrapper with "
            "its own identity. Exists so a candidate-versus-incumbent evaluation "
            "with distinct team identities must still cancel to exactly zero. Not "
            "a proposal and never promotable."
        ),
    ),
    ResearchCandidate(
        candidate_key="research_legal_shift_v1",
        base_profile_key="partner_aware_lead_v2",
        override=_LEGAL_SHIFT,
        is_calibration_control=True,
        description=(
            "The incumbent with its trick-play choice moved one position along the "
            "engine's stable legal ordering whenever more than one action is "
            "legal. A deliberately different, deliberately unmotivated policy "
            "whose only purpose is to show the pipeline detects a real difference. "
            "Expected to play worse. Not a proposal and never promotable."
        ),
    ),
)


CANDIDATE_KEYS: tuple[str, ...] = tuple(item.candidate_key for item in _CANDIDATES)


def research_candidates() -> dict[str, ResearchCandidate]:
    return {item.candidate_key: item for item in _CANDIDATES}


def _base_specification(base_profile_key: str) -> AgentSpecification:
    from .improved_registry import improved_specifications_by_profile_key
    from .registry import phase4_specifications_by_profile_key

    improved = improved_specifications_by_profile_key()
    if base_profile_key in improved:
        return improved[base_profile_key]
    phase4 = phase4_specifications_by_profile_key()
    if base_profile_key in phase4:
        return phase4[base_profile_key]
    raise AgentsValidationError(f"unknown base profile {base_profile_key!r}")


def candidate_configuration(candidate: ResearchCandidate) -> dict[str, object]:
    """The identity-bearing configuration: base address plus override."""

    base = _base_specification(candidate.base_profile_key)
    return {
        "base_agent_id": base.agent_id,
        "base_configuration_digest": base.configuration_digest,
        "base_profile_key": candidate.base_profile_key,
        "candidate_key": candidate.candidate_key,
        "is_calibration_control": candidate.is_calibration_control,
        "override": candidate.override.to_data(),
        "schema_version": RESEARCH_CANDIDATE_SCHEMA_VERSION,
    }


def specification_for_candidate(candidate: ResearchCandidate) -> AgentSpecification:
    """Content-addressed specification. A changed parameter mints a new identity."""

    base = _base_specification(candidate.base_profile_key)
    return AgentSpecification.build(
        agent_family=f"research_candidate_{candidate.candidate_key}",
        configuration_version=RESEARCH_CANDIDATE_SCHEMA_VERSION,
        implementation_reference=candidate.implementation_reference,
        ruleset_compatibility=base.ruleset_compatibility,
        observation_schema_compatibility=base.observation_schema_compatibility,
        determinism=DeterminismClass.DETERMINISTIC,
        seed_policy=SeedPolicy.NONE,
        configuration=candidate_configuration(candidate),
        model_checkpoint_id=None,
        search_budget=None,
        partner_convention_id=base.partner_convention_id,
        description=candidate.description,
    )


def candidate_specifications_by_key() -> dict[str, AgentSpecification]:
    return {
        item.candidate_key: specification_for_candidate(item) for item in _CANDIDATES
    }


def _construct_base(base_profile_key: str, *, seat: int) -> Agent:
    from .factory import construct_registered_agent
    from .improved_registry import (
        improved_agent_from_specification,
        improved_specifications_by_profile_key,
    )

    improved = improved_specifications_by_profile_key()
    if base_profile_key in improved:
        return improved_agent_from_specification(
            improved[base_profile_key], profile_key=base_profile_key, seat=seat
        )
    return construct_registered_agent(
        _base_specification(base_profile_key), seat=seat
    )


def construct_candidate_agent(
    specification: AgentSpecification, *, seat: int
) -> Agent:
    """Build a declared candidate for one seat, from its own specification.

    Refuses any specification that is not byte-for-byte the declared one, so an
    edited or forged candidate cannot be evaluated under a declared identity.
    """

    if type(seat) is not int or seat not in range(4):
        raise AgentConstructionError("candidate construction seat must be in 0..3")
    reference = getattr(specification, "implementation_reference", None)
    if not isinstance(reference, str) or not reference.startswith(REFERENCE_PREFIX):
        raise AgentConstructionError(
            f"{reference!r} is not a research-candidate reference"
        )
    key = reference[len(REFERENCE_PREFIX):]
    declared = research_candidates().get(key)
    if declared is None:
        raise AgentConstructionError(f"undeclared research candidate {key!r}")
    expected = specification_for_candidate(declared)
    if expected != specification:
        raise AgentConstructionError(
            "research candidate specification disagrees with its declared entry"
        )
    implementation = OVERRIDE_IMPLEMENTATIONS.get(declared.override.override_id)
    if implementation is None:
        raise AgentConstructionError(
            f"declared override {declared.override.override_id!r} has no implementation"
        )
    return implementation(
        agent_id=specification.agent_id,
        base=_construct_base(declared.base_profile_key, seat=seat),
        parameters=dict(declared.override.parameters),
    )


def is_research_candidate_reference(reference: object) -> bool:
    return isinstance(reference, str) and reference.startswith(REFERENCE_PREFIX)


__all__ = [
    "CANDIDATE_KEYS",
    "REFERENCE_PREFIX",
    "RESEARCH_CANDIDATE_SCHEMA_VERSION",
    "CandidateOverride",
    "ResearchCandidate",
    "candidate_configuration",
    "candidate_specifications_by_key",
    "construct_candidate_agent",
    "is_research_candidate_reference",
    "research_candidates",
    "specification_for_candidate",
]
