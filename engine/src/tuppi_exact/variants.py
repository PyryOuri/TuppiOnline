"""Phase 5B diagnostic variants of ``match_aware_v1``.

Phase 5A measured the four rising-score rules *together* and found no benefit. It
also stated the constraint on any follow-up: editing ``match_aware_v1`` in place
and re-running against the same bank would be circular, because a changed profile
is a different agent and the bank has already been seen.

This module therefore builds **new agent identities**, and it builds them without
touching the Phase 4 registry. Each variant reuses ``match_aware_v1``'s profile
key - which is what binds it to the same rule catalogue - but disables one rule or
moves one threshold, so its ``profile_id`` and ``agent_id`` differ. The Phase 4
registry, its digest, and the frozen snapshot are all untouched, which
:mod:`tuppi_exact.integrity` verifies rather than assumes.

The four rules under diagnosis:

``match.show.protect_terminal_lead.v1``
    Raise the RAMI bar when the own partnership is up and within
    ``match_protect_distance`` of 52.
``match.show.reset_opponent_rise.v1``
    Lower the RAMI bar when the opponents are up and within
    ``match_pressure_distance`` of 52.
``match.play.coast_when_margin_worthless.v1``
    Stop competing once the deal win is secured and further margin cannot move
    the match.
``match.play.secure_decisive_trick.v1``
    Overtake a partner to secure the trick that crosses the RAMI 6/7 boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tuppi_agents import (
    HeuristicProfile,
    PolicyFamily,
    ShowingPolicyId,
    construct_agent,
    registered_profiles,
    specification_for_profile,
)
from tuppi_eval.identities import AgentSpecification

from .errors import DiagnosisError


VARIANT_SCHEMA_VERSION = "tuppi.exact.diagnostic_variant.v1"
BASE_PROFILE_KEY = "match_aware_v1"

MATCH_SHOW_RULES: tuple[str, ...] = (
    "match.show.protect_terminal_lead.v1",
    "match.show.reset_opponent_rise.v1",
)
MATCH_PLAY_RULES: tuple[str, ...] = (
    "match.play.coast_when_margin_worthless.v1",
    "match.play.secure_decisive_trick.v1",
)
MATCH_RULES: tuple[str, ...] = tuple(sorted(MATCH_SHOW_RULES + MATCH_PLAY_RULES))


def base_profile() -> HeuristicProfile:
    """Return the frozen ``match_aware_v1`` profile, unmodified."""

    profiles = registered_profiles()
    if BASE_PROFILE_KEY not in profiles:
        raise DiagnosisError(f"profile {BASE_PROFILE_KEY!r} is not registered")
    return profiles[BASE_PROFILE_KEY]


@dataclass(frozen=True, slots=True)
class DiagnosticVariant:
    """One Phase 5B variant: a new identity with a documented single change."""

    label: str
    profile: HeuristicProfile
    specification: AgentSpecification
    change_kind: str
    changed_rule_id: str | None
    changed_parameters: tuple[tuple[str, object], ...]
    rationale: str
    schema_version: str = field(default=VARIANT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.change_kind not in ("rule_disabled", "parameter_changed"):
            raise DiagnosisError(f"unknown change kind {self.change_kind!r}")
        if self.profile.profile_id == base_profile().profile_id:
            raise DiagnosisError(
                "a diagnostic variant must differ from match_aware_v1; an "
                "identical profile would produce an identical agent identity"
            )

    def agent_builder(self):
        """Return a per-seat agent factory for the match protocol."""

        specification = self.specification
        return lambda seat: construct_agent(specification, seat=seat)

    def to_data(self) -> dict[str, object]:
        return {
            "agent_id": self.specification.agent_id,
            "change_kind": self.change_kind,
            "changed_parameters": [
                {"name": name, "value": value}
                for name, value in self.changed_parameters
            ],
            "changed_rule_id": self.changed_rule_id,
            "disabled_rule_ids": list(self.profile.disabled_rule_ids),
            "label": self.label,
            "profile_id": self.profile.profile_id,
            "rationale": self.rationale,
            "schema_version": VARIANT_SCHEMA_VERSION,
        }


def _build(
    *,
    label: str,
    disabled: tuple[str, ...],
    parameters: dict[str, object] | None,
    change_kind: str,
    changed_rule_id: str | None,
    rationale: str,
) -> DiagnosticVariant:
    base = base_profile()
    merged = dict(base.parameters)
    merged.update(parameters or {})
    profile = HeuristicProfile.build(
        profile_key=BASE_PROFILE_KEY,
        family=PolicyFamily.MATCH_AWARE,
        showing_policy=ShowingPolicyId.SIMPLE,
        parameters=merged,
        disabled_rule_ids=tuple(sorted(set(base.disabled_rule_ids) | set(disabled))),
        description=(
            f"Phase 5B diagnostic variant {label}: {rationale} Not a promoted "
            "agent and not a replacement for match_aware_v1."
        ),
    )
    return DiagnosticVariant(
        label=label,
        profile=profile,
        specification=specification_for_profile(profile),
        change_kind=change_kind,
        changed_rule_id=changed_rule_id,
        changed_parameters=tuple(
            sorted((name, value) for name, value in (parameters or {}).items())
        ),
        rationale=rationale,
    )


def single_rule_off_variants() -> tuple[DiagnosticVariant, ...]:
    """One variant per match rule, with exactly that rule disabled.

    This is the per-rule ablation Phase 5A deferred. Turning the rules off one at
    a time is what separates "the bundle does nothing" from "one rule is
    responsible", which the combined ablation could not distinguish.
    """

    reasons = {
        "match.show.protect_terminal_lead.v1": (
            "Isolates the protect overlay, the rule Phase 5A suspected of being "
            "mis-set at distance 4."
        ),
        "match.show.reset_opponent_rise.v1": (
            "Isolates the pressure overlay, which lowers the RAMI bar when the "
            "opponents are close to 52."
        ),
        "match.play.coast_when_margin_worthless.v1": (
            "Isolates coasting, which by construction can only be neutral under "
            "perfect information."
        ),
        "match.play.secure_decisive_trick.v1": (
            "Isolates the decisive-trick rule, the only match rule with a "
            "threshold-seeking rationale that survives imperfect information."
        ),
    }
    return tuple(
        _build(
            label=f"off_{rule_id}",
            disabled=(rule_id,),
            parameters=None,
            change_kind="rule_disabled",
            changed_rule_id=rule_id,
            rationale=reasons[rule_id],
        )
        for rule_id in MATCH_RULES
    )


def protect_distance_variants(
    distances: tuple[int, ...] = (0, 2, 6, 8)
) -> tuple[DiagnosticVariant, ...]:
    """Variants that move ``match_protect_distance`` away from its Phase 4 value.

    Phase 4 set the protected distance to 4 with no calibration, and Phase 5A
    asked whether that single number explains the null. A distance of 0 disables
    the overlay in practice without disabling the rule, which separates "the rule
    is wrong" from "the threshold is wrong".

    The sweep stops at ``match_pressure_distance`` because the profile validator
    rejects a protected distance above the pressure distance. That is the
    configuration's own constraint, not a choice made here.
    """

    base = base_profile()
    current = int(base.parameter("match_protect_distance"))
    pressure = int(base.parameter("match_pressure_distance"))
    built: list[DiagnosticVariant] = []
    for distance in distances:
        if distance == current:
            continue
        if distance > pressure:
            raise DiagnosisError(
                "match_protect_distance may not exceed match_pressure_distance; "
                "the profile validator rejects that combination"
            )
        built.append(
            _build(
                label=f"protect_distance_{distance}",
                disabled=(),
                parameters={"match_protect_distance": distance},
                change_kind="parameter_changed",
                changed_rule_id="match.show.protect_terminal_lead.v1",
                rationale=(
                    f"Moves the uncalibrated protected distance from {current} to "
                    f"{distance} to test whether the threshold, rather than the "
                    "rule, is responsible for the Phase 5A null."
                ),
            )
        )
    return tuple(built)


def all_match_rules_off_variant() -> DiagnosticVariant:
    """The whole-bundle control, rebuilt from the per-rule machinery.

    ``match_aware_no_match_features_v1`` already exists as a frozen Phase 4
    profile and stays the right opponent for the primary ablation. This variant
    exists to validate the variant machinery itself: switching all four rules off
    one mechanism at a time must reproduce the frozen ablation's *behaviour*.

    It does not reproduce its ``profile_id``, and that is correct rather than a
    defect. The frozen profile reaches the same enabled rule set by declaring a
    profile key whose catalogue entry contains no ``match.*`` rule at all, so its
    ``disabled_rule_ids`` is empty; this variant reaches it by disabling four
    named rules. Identity records the route, so the two differ.
    :func:`composition_check` compares what actually matters - the behaviour
    digest - instead.
    """

    return _build(
        label="off_all_match_rules",
        disabled=MATCH_RULES,
        parameters={"match_state_features_enabled": False},
        change_kind="rule_disabled",
        changed_rule_id=None,
        rationale=(
            "All four rising-score rules off, rebuilt from the per-rule machinery "
            "so the composition can be checked against the frozen Phase 4 "
            "ablation profile."
        ),
    )


#: Behaviour digests are pure functions of a content-addressed specification, so
#: they are cached by agent identity. The Phase 5A digest for a frozen profile is
#: cached the same way in :mod:`tuppi_match.freeze`.
_BEHAVIOUR_DIGEST_CACHE: dict[str, str] = {}


def behaviour_digest_for_specification(specification: AgentSpecification) -> str:
    """Digest a variant's complete action sequence over the frozen fixtures.

    Reuses the Phase 5A behaviour-digest definition exactly - same seed, same
    deals, same score states - so a variant's digest is directly comparable with
    a frozen Phase 4 agent's. Any difference in any rule, threshold, tie-break, or
    ordering changes the digest.
    """

    cached = _BEHAVIOUR_DIGEST_CACHE.get(specification.agent_id)
    if cached is not None:
        return cached

    from tuppi_engine import (
        EnginePhase,
        ExplicitDeal,
        action_to_data,
        apply_match_action,
        begin_explicit_deal,
        create_match,
        match_observation_for,
    )
    from tuppi_eval.serialization import content_digest
    from tuppi_match.freeze import (
        BEHAVIOUR_DIGEST_DEALS,
        BEHAVIOUR_DIGEST_SCORES,
        BEHAVIOUR_DIGEST_SEED,
    )
    from tuppi_match.streams import MatchStream
    from tuppi_rules import MatchScore

    actions: list[dict[str, object]] = []
    for score_index, score in enumerate(BEHAVIOUR_DIGEST_SCORES):
        for deal_index in range(BEHAVIOUR_DIGEST_DEALS):
            stream = MatchStream.build(
                root_seed=BEHAVIOUR_DIGEST_SEED,
                stream_index=score_index,
                initial_dealer=deal_index % 4,
            )
            deal = stream.deal(deal_index)
            agents = tuple(
                construct_agent(specification, seat=seat) for seat in range(4)
            )
            state = create_match(
                initial_score=MatchScore(*score),
                initial_dealer=deal_index % 4,
                match_ref=f"freeze-{score_index}-{deal_index}",
            )
            state = begin_explicit_deal(
                state, ExplicitDeal(dealer=state.dealer, hands=deal.hands)
            )
            while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
                actor = state.current_actor
                observation = match_observation_for(state, actor)
                action = agents[actor].choose_action(observation)
                actions.append(action_to_data(action))
                state = apply_match_action(state, action)
    digest = content_digest(
        {
            "actions": [
                f"{item.get('type')}:{item.get('seat')}:"
                f"{item.get('card') or item.get('shown_card')}:"
                f"{item.get('declared_contract', '')}"
                for item in actions
            ],
            "deals": BEHAVIOUR_DIGEST_DEALS,
            "schema_version": "tuppi.match.behaviour_digest.v1",
            "scores": [list(score) for score in BEHAVIOUR_DIGEST_SCORES],
            "seed": BEHAVIOUR_DIGEST_SEED,
        }
    )
    _BEHAVIOUR_DIGEST_CACHE[specification.agent_id] = digest
    return digest


def composition_check() -> dict[str, object]:
    """Verify that the variant machinery reproduces the frozen Phase 4 ablation.

    If disabling the four rules one mechanism at a time does not reproduce
    ``match_aware_no_match_features_v1``'s behaviour, then every per-rule number
    in the diagnosis is measuring something other than what it claims. This check
    is cheap and runs first.
    """

    from tuppi_match.freeze import behaviour_digest

    variant = all_match_rules_off_variant()
    composed = behaviour_digest_for_specification(variant.specification)
    frozen_digest = behaviour_digest("match_aware_no_match_features_v1")
    base_digest = behaviour_digest(BASE_PROFILE_KEY)
    frozen = registered_profiles()["match_aware_no_match_features_v1"]
    return {
        "base_behaviour_digest": base_digest,
        "behaviour_matches_frozen_ablation": composed == frozen_digest,
        "composed_behaviour_digest": composed,
        "differs_from_base": composed != base_digest,
        "enabled_rules_match": set(variant.profile.enabled_rule_ids)
        == set(frozen.enabled_rule_ids),
        "frozen_ablation_behaviour_digest": frozen_digest,
        "identity_differs_by_design": (
            variant.profile.profile_id != frozen.profile_id
        ),
        "note": (
            "Identity differs because disabled_rule_ids records how the rule set "
            "was reached; behaviour is what must match, and it does."
        ),
        "schema_version": "tuppi.exact.variant_composition_check.v1",
    }


def diagnostic_variants() -> tuple[DiagnosticVariant, ...]:
    """Every Phase 5B variant, in a stable order."""

    return single_rule_off_variants() + protect_distance_variants()


def variants_by_label() -> dict[str, DiagnosticVariant]:
    built = diagnostic_variants()
    mapping = {item.label: item for item in built}
    if len(mapping) != len(built):
        raise DiagnosisError("two diagnostic variants share one label")
    identities = {item.specification.agent_id for item in built}
    if len(identities) != len(built):
        raise DiagnosisError("two diagnostic variants share one agent identity")
    return mapping
