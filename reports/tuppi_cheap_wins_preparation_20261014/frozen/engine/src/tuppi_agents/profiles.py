"""Strict, versioned, immutable, identity-bearing heuristic profiles.

A profile is the complete behavioural configuration of one Phase 4 policy: the
family whose rules it runs, which optional rules are switched off, which
showing policy it uses, and the numeric parameters those rules read. Profiles
are canonicalized and content-addressed, so any behaviourally material change
produces a different ``profile_id`` and therefore a different agent ID.

The framework is deliberately *not* a general strategy language. It supports
exactly the finite Phase 4 families, rejects unknown fields, and rejects
settings that contradict each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
import json
from typing import Any

from tuppi_rules import MATCH_TARGET

from .errors import ProfileError
from .ordering import (
    CANONICAL_SUIT_PRECEDENCE_ID,
    LEGACY_SUIT_PRECEDENCE_ID,
)
from .rule_catalogue import require_rule, rules_for_profile


PROFILE_SCHEMA_VERSION = "tuppi.agents.heuristic_profile.v1"
LEGACY_CONVENTION_RULE = "partner.legacy.minimum_information_show.v1"
LEGACY_CONVENTION_ID = "legacy_min_information_show_v1"


class ShowingPolicyId(StrEnum):
    LEGACY = "legacy_show_v1"
    SIMPLE = "simple_show_v1"


class PolicyFamily(StrEnum):
    LEGACY_HEURISTIC_PORT = "legacy_heuristic_port"
    REACTIVE_CONTRACT = "reactive_contract"
    PUBLIC_COUNTING = "public_counting"
    PARTNER_AWARE = "partner_aware"
    MATCH_AWARE = "match_aware"


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    name: str
    kind: str
    default: Any
    minimum: float | None = None
    maximum: float | None = None

    def validate(self, value: object) -> int | float | bool:
        if self.kind == "bool":
            if type(value) is not bool:
                raise ProfileError(f"parameter {self.name!r} must be a boolean")
            return value
        if self.kind == "int":
            if type(value) is not int or isinstance(value, bool):
                raise ProfileError(f"parameter {self.name!r} must be an integer")
            numeric: float = float(value)
        elif self.kind == "float":
            if type(value) not in (int, float) or isinstance(value, bool):
                raise ProfileError(f"parameter {self.name!r} must be a number")
            numeric = float(value)
        else:  # pragma: no cover - guarded by the family tables below
            raise ProfileError(f"parameter {self.name!r} has an unknown kind")
        if self.minimum is not None and numeric < self.minimum:
            raise ProfileError(
                f"parameter {self.name!r} must be at least {self.minimum}"
            )
        if self.maximum is not None and numeric > self.maximum:
            raise ProfileError(
                f"parameter {self.name!r} must be at most {self.maximum}"
            )
        return value if self.kind == "int" else numeric


_LEGACY_SHOW_PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec("legacy_protected_score", "int", 40, minimum=0, maximum=MATCH_TARGET),
    ParameterSpec("legacy_rami_ev_margin", "float", 0.5, minimum=0.0, maximum=20.0),
    ParameterSpec(
        "legacy_rami_ev_minimum_pressured", "float", 3.0, minimum=-28.0, maximum=28.0
    ),
    ParameterSpec(
        "legacy_rami_ev_minimum_protected", "float", 6.0, minimum=-28.0, maximum=28.0
    ),
    ParameterSpec(
        "legacy_rami_ev_minimum_table", "float", 4.0, minimum=-28.0, maximum=28.0
    ),
)

_SIMPLE_SHOW_PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec("simple_nolo_veto_threshold", "float", 2.0, minimum=-40.0, maximum=40.0),
    ParameterSpec("simple_rami_threshold", "float", 15.0, minimum=0.0, maximum=60.0),
)

_MATCH_STATE_PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec("match_state_features_enabled", "bool", True),
    ParameterSpec(
        "match_pressure_distance", "int", 8, minimum=0, maximum=MATCH_TARGET
    ),
    ParameterSpec(
        "match_pressure_threshold_discount", "float", 2.0, minimum=0.0, maximum=28.0
    ),
    ParameterSpec("match_protect_distance", "int", 4, minimum=0, maximum=MATCH_TARGET),
    ParameterSpec(
        "match_protect_threshold_bonus", "float", 3.0, minimum=0.0, maximum=28.0
    ),
)

# Score components are compared lexicographically, so a magnitude only matters
# inside its own component. ``rami_lead_length_bonus`` is the only genuine
# weight in Phase 4 play: it trades suit length against high-card weight inside
# a single component. Rule priority is expressed by component order, and
# switching a rule off is expressed by ``disabled_rule_ids``, never by scaling
# a lexicographic tier to zero.
_REACTIVE_PLAY_PARAMETERS: tuple[ParameterSpec, ...] = (
    ParameterSpec("rami_lead_length_bonus", "float", 0.5, minimum=0.0, maximum=5.0),
)


@dataclass(frozen=True, slots=True)
class FamilySpec:
    family: PolicyFamily
    implementation_reference: str
    profile_key: str
    play_parameters: tuple[ParameterSpec, ...]
    allowed_showing_policies: tuple[ShowingPolicyId, ...]
    uses_public_inference: bool
    uses_partner_rules: bool
    supports_match_state: bool
    summary: str


FAMILY_SPECS: dict[PolicyFamily, FamilySpec] = {
    PolicyFamily.LEGACY_HEURISTIC_PORT: FamilySpec(
        family=PolicyFamily.LEGACY_HEURISTIC_PORT,
        implementation_reference="tuppi_agents.factory:legacy_heuristic_port_v1",
        profile_key="legacy_heuristic_port_v1",
        play_parameters=(),
        allowed_showing_policies=(ShowingPolicyId.LEGACY,),
        uses_public_inference=False,
        uses_partner_rules=False,
        supports_match_state=False,
        summary=(
            "Faithful port of the useful public-information parts of the frozen "
            "legacy heuristic, adapted to project_target_v1."
        ),
    ),
    PolicyFamily.REACTIVE_CONTRACT: FamilySpec(
        family=PolicyFamily.REACTIVE_CONTRACT,
        implementation_reference="tuppi_agents.factory:reactive_contract_v1",
        profile_key="reactive_contract_v1",
        play_parameters=_REACTIVE_PLAY_PARAMETERS,
        allowed_showing_policies=(ShowingPolicyId.SIMPLE, ShowingPolicyId.LEGACY),
        uses_public_inference=False,
        uses_partner_rules=False,
        supports_match_state=False,
        summary=(
            "Contract-aware baseline using only its own hand, the current trick, "
            "seat relations, and the legal action set."
        ),
    ),
    PolicyFamily.PUBLIC_COUNTING: FamilySpec(
        family=PolicyFamily.PUBLIC_COUNTING,
        implementation_reference="tuppi_agents.factory:public_counting_v1",
        profile_key="public_counting_v1",
        play_parameters=_REACTIVE_PLAY_PARAMETERS,
        allowed_showing_policies=(ShowingPolicyId.SIMPLE,),
        uses_public_inference=True,
        uses_partner_rules=False,
        supports_match_state=False,
        summary=(
            "Reactive baseline extended with hard public inference: proven voids, "
            "public card accounting, and certain-winner deductions."
        ),
    ),
    PolicyFamily.PARTNER_AWARE: FamilySpec(
        family=PolicyFamily.PARTNER_AWARE,
        implementation_reference="tuppi_agents.factory:partner_aware_v1",
        profile_key="partner_aware_v1",
        play_parameters=_REACTIVE_PLAY_PARAMETERS,
        allowed_showing_policies=(ShowingPolicyId.SIMPLE,),
        uses_public_inference=True,
        uses_partner_rules=True,
        supports_match_state=False,
        summary=(
            "Public-counting baseline extended with explicit partnership rules for "
            "both contracts."
        ),
    ),
    PolicyFamily.MATCH_AWARE: FamilySpec(
        family=PolicyFamily.MATCH_AWARE,
        implementation_reference="tuppi_agents.factory:match_aware_v1",
        profile_key="match_aware_v1",
        play_parameters=_REACTIVE_PLAY_PARAMETERS,
        allowed_showing_policies=(ShowingPolicyId.SIMPLE,),
        uses_public_inference=True,
        uses_partner_rules=True,
        supports_match_state=True,
        summary=(
            "Partner-aware baseline extended with explicit rising-score awareness "
            "under deterministic rules only."
        ),
    ),
}


def _showing_parameters(policy: ShowingPolicyId) -> tuple[ParameterSpec, ...]:
    if policy is ShowingPolicyId.LEGACY:
        return _LEGACY_SHOW_PARAMETERS
    return _SIMPLE_SHOW_PARAMETERS


def parameter_specs(
    family: PolicyFamily, showing_policy: ShowingPolicyId
) -> tuple[ParameterSpec, ...]:
    spec = FAMILY_SPECS[family]
    specs = spec.play_parameters + _showing_parameters(showing_policy)
    if spec.supports_match_state:
        specs = specs + _MATCH_STATE_PARAMETERS
    return tuple(sorted(specs, key=lambda item: item.name))


@dataclass(frozen=True, slots=True)
class HeuristicProfile:
    """An immutable content-addressed behavioural configuration."""

    profile_id: str
    profile_key: str
    family: PolicyFamily
    profile_version: str
    showing_policy: ShowingPolicyId
    parameters_json: str
    disabled_rule_ids: tuple[str, ...]
    enabled_rule_ids: tuple[str, ...]
    uses_public_inference: bool
    uses_partner_rules: bool
    match_state_enabled: bool
    partner_convention_id: str | None
    show_tie_break_id: str
    description: str
    schema_version: str = field(default=PROFILE_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.family, PolicyFamily):
            raise ProfileError("family must be a PolicyFamily value")
        if not isinstance(self.showing_policy, ShowingPolicyId):
            raise ProfileError("showing_policy must be a ShowingPolicyId value")
        spec = FAMILY_SPECS[self.family]
        if self.showing_policy not in spec.allowed_showing_policies:
            raise ProfileError(
                f"family {self.family.value!r} does not support showing policy "
                f"{self.showing_policy.value!r}"
            )
        if not isinstance(self.profile_key, str) or not self.profile_key:
            raise ProfileError("profile_key must be a nonempty string")
        if not isinstance(self.profile_version, str) or not self.profile_version:
            raise ProfileError("profile_version must be a nonempty string")
        if not isinstance(self.description, str) or not self.description:
            raise ProfileError("description must be nonempty")
        try:
            parameters = json.loads(self.parameters_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ProfileError("parameters_json is not valid JSON") from exc
        if type(parameters) is not dict:
            raise ProfileError("profile parameters must be a JSON object")
        if _canonical_text(parameters) != self.parameters_json:
            raise ProfileError("parameters_json must be canonical")
        _validate_parameters(self.family, self.showing_policy, parameters)

        for label, value in (
            ("disabled_rule_ids", self.disabled_rule_ids),
            ("enabled_rule_ids", self.enabled_rule_ids),
        ):
            if type(value) is not tuple:
                raise ProfileError(f"{label} must be an immutable tuple")
            if tuple(sorted(set(value))) != value:
                raise ProfileError(f"{label} must be sorted and unique")
        family_rules = {rule.rule_id: rule for rule in rules_for_profile(self.profile_key)}
        if not family_rules:
            raise ProfileError(
                f"no catalogued rule declares profile {self.profile_key!r}"
            )
        for rule_id in self.disabled_rule_ids:
            rule = require_rule(rule_id)
            if rule_id not in family_rules:
                raise ProfileError(
                    f"rule {rule_id!r} is not part of profile {self.profile_key!r}"
                )
            if not rule.independently_disableable:
                raise ProfileError(f"rule {rule_id!r} cannot be disabled")
        expected_enabled = tuple(
            sorted(set(family_rules) - set(self.disabled_rule_ids))
        )
        if self.enabled_rule_ids != expected_enabled:
            raise ProfileError(
                "enabled_rule_ids must be the family rules minus the disabled rules"
            )

        if self.uses_public_inference is not spec.uses_public_inference:
            raise ProfileError("public-inference capability disagrees with the family")
        if self.uses_partner_rules is not spec.uses_partner_rules:
            raise ProfileError("partner-rule capability disagrees with the family")
        if type(self.match_state_enabled) is not bool:
            raise ProfileError("match_state_enabled must be a boolean")
        if self.match_state_enabled and not spec.supports_match_state:
            raise ProfileError(
                "match-state features are enabled for a family that has none"
            )
        if spec.supports_match_state:
            declared = bool(parameters["match_state_features_enabled"])
            if declared is not self.match_state_enabled:
                raise ProfileError(
                    "match_state_enabled contradicts match_state_features_enabled"
                )
            match_rules = tuple(
                rule_id for rule_id in family_rules if rule_id.startswith("match.")
            )
            disabled_match = set(self.disabled_rule_ids) & set(match_rules)
            if not self.match_state_enabled and disabled_match != set(match_rules):
                raise ProfileError(
                    "disabling match-state features requires every match rule off"
                )
            if self.match_state_enabled and disabled_match == set(match_rules):
                raise ProfileError(
                    "every match rule is off while match-state features are enabled"
                )

        convention_enabled = LEGACY_CONVENTION_RULE in self.enabled_rule_ids
        if convention_enabled:
            if self.partner_convention_id != LEGACY_CONVENTION_ID:
                raise ProfileError(
                    "the legacy showing convention requires its convention ID"
                )
            if self.show_tie_break_id != LEGACY_SUIT_PRECEDENCE_ID:
                raise ProfileError(
                    "the legacy showing convention requires legacy suit precedence"
                )
        else:
            if self.partner_convention_id is not None:
                raise ProfileError(
                    "a partner convention ID requires an enabled convention rule"
                )
            expected_tie_break = (
                LEGACY_SUIT_PRECEDENCE_ID
                if self.showing_policy is ShowingPolicyId.LEGACY
                else CANONICAL_SUIT_PRECEDENCE_ID
            )
            if self.show_tie_break_id != expected_tie_break:
                raise ProfileError(
                    "show_tie_break_id disagrees with the configured showing policy"
                )

        expected_id = f"profile:{_digest(self.identity_data())}"
        if self.profile_id != expected_id:
            raise ProfileError("profile_id disagrees with the behavioural content")

    # ---------------------------------------------------------------- builders

    @classmethod
    def build(
        cls,
        *,
        profile_key: str,
        family: PolicyFamily,
        profile_version: str = "1.0.0",
        showing_policy: ShowingPolicyId,
        parameters: dict[str, Any] | None = None,
        disabled_rule_ids: tuple[str, ...] = (),
        description: str,
        claimed_profile_id: str | None = None,
    ) -> "HeuristicProfile":
        spec = FAMILY_SPECS[family]
        specs = parameter_specs(family, showing_policy)
        supplied = dict(parameters or {})
        unknown = set(supplied) - {item.name for item in specs}
        if unknown:
            raise ProfileError(
                f"unknown profile parameter(s): {sorted(unknown)}"
            )
        resolved = {
            item.name: supplied.get(item.name, item.default) for item in specs
        }
        _validate_parameters(family, showing_policy, resolved)
        match_state = (
            bool(resolved["match_state_features_enabled"])
            if spec.supports_match_state
            else False
        )
        disabled = set(disabled_rule_ids)
        if spec.supports_match_state and not match_state:
            disabled |= {
                rule.rule_id
                for rule in rules_for_profile(profile_key)
                if rule.rule_id.startswith("match.")
            }
        disabled_tuple = tuple(sorted(disabled))
        family_rule_ids = {rule.rule_id for rule in rules_for_profile(profile_key)}
        enabled = tuple(sorted(family_rule_ids - disabled))
        convention = LEGACY_CONVENTION_RULE in enabled
        tie_break = (
            LEGACY_SUIT_PRECEDENCE_ID
            if convention or showing_policy is ShowingPolicyId.LEGACY
            else CANONICAL_SUIT_PRECEDENCE_ID
        )
        values = {
            "profile_key": profile_key,
            "family": family,
            "profile_version": profile_version,
            "showing_policy": showing_policy,
            "parameters_json": _canonical_text(resolved),
            "disabled_rule_ids": disabled_tuple,
            "enabled_rule_ids": enabled,
            "uses_public_inference": spec.uses_public_inference,
            "uses_partner_rules": spec.uses_partner_rules,
            "match_state_enabled": match_state,
            "partner_convention_id": LEGACY_CONVENTION_ID if convention else None,
            "show_tie_break_id": tie_break,
            "description": description,
        }
        provisional = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        object.__setattr__(provisional, "schema_version", PROFILE_SCHEMA_VERSION)
        computed = f"profile:{_digest(provisional.identity_data())}"
        return cls(profile_id=claimed_profile_id or computed, **values)

    # ----------------------------------------------------------------- access

    @property
    def parameters(self) -> dict[str, Any]:
        return json.loads(self.parameters_json)

    def parameter(self, name: str) -> Any:
        values = self.parameters
        if name not in values:
            raise ProfileError(f"profile has no parameter {name!r}")
        return values[name]

    def rule_enabled(self, rule_id: str) -> bool:
        require_rule(rule_id)
        return rule_id in self.enabled_rule_ids

    @property
    def implementation_reference(self) -> str:
        return FAMILY_SPECS[self.family].implementation_reference

    def identity_data(self) -> dict[str, object]:
        """Behaviourally material content only; the description is excluded."""

        return {
            "disabled_rule_ids": list(self.disabled_rule_ids),
            "enabled_rule_ids": list(self.enabled_rule_ids),
            "family": self.family.value,
            "match_state_enabled": self.match_state_enabled,
            "parameters": json.loads(self.parameters_json),
            "partner_convention_id": self.partner_convention_id,
            "profile_version": self.profile_version,
            "schema_version": PROFILE_SCHEMA_VERSION,
            "show_tie_break_id": self.show_tie_break_id,
            "showing_policy": self.showing_policy.value,
            "uses_partner_rules": self.uses_partner_rules,
            "uses_public_inference": self.uses_public_inference,
        }

    def to_data(self) -> dict[str, object]:
        return {
            **self.identity_data(),
            "description": self.description,
            "implementation_reference": self.implementation_reference,
            "profile_id": self.profile_id,
            "profile_key": self.profile_key,
        }


def profile_from_data(value: object) -> HeuristicProfile:
    """Parse a profile with no tolerance for unknown or missing fields."""

    if type(value) is not dict:
        raise ProfileError("a profile must be a JSON object")
    expected = {
        "description",
        "disabled_rule_ids",
        "enabled_rule_ids",
        "family",
        "implementation_reference",
        "match_state_enabled",
        "parameters",
        "partner_convention_id",
        "profile_id",
        "profile_key",
        "profile_version",
        "schema_version",
        "show_tie_break_id",
        "showing_policy",
        "uses_partner_rules",
        "uses_public_inference",
    }
    actual = set(value)
    if actual != expected:
        raise ProfileError(
            "profile fields differ; "
            f"missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}"
        )
    if value["schema_version"] != PROFILE_SCHEMA_VERSION:
        raise ProfileError("unsupported profile schema_version")
    try:
        family = PolicyFamily(value["family"])
        showing = ShowingPolicyId(value["showing_policy"])
    except (TypeError, ValueError) as exc:
        raise ProfileError("profile family or showing policy is invalid") from exc
    raw_disabled = value["disabled_rule_ids"]
    if type(raw_disabled) is not list or any(
        not isinstance(item, str) for item in raw_disabled
    ):
        raise ProfileError("disabled_rule_ids must be a string array")
    parameters = value["parameters"]
    if type(parameters) is not dict:
        raise ProfileError("profile parameters must be a JSON object")
    spec = FAMILY_SPECS[family]
    explicit = tuple(
        rule_id
        for rule_id in sorted(raw_disabled)
        if not (
            spec.supports_match_state
            and rule_id.startswith("match.")
            and not bool(parameters.get("match_state_features_enabled", True))
        )
    )
    profile = HeuristicProfile.build(
        profile_key=value["profile_key"],
        family=family,
        profile_version=value["profile_version"],
        showing_policy=showing,
        parameters=parameters,
        disabled_rule_ids=explicit,
        description=value["description"],
        claimed_profile_id=value["profile_id"],
    )
    if list(profile.disabled_rule_ids) != sorted(raw_disabled):
        raise ProfileError("disabled_rule_ids disagree with the derived rule set")
    if list(profile.enabled_rule_ids) != value["enabled_rule_ids"]:
        raise ProfileError("enabled_rule_ids disagree with the derived rule set")
    if profile.implementation_reference != value["implementation_reference"]:
        raise ProfileError("implementation_reference disagrees with the family")
    for name in (
        "match_state_enabled",
        "partner_convention_id",
        "show_tie_break_id",
        "uses_partner_rules",
        "uses_public_inference",
    ):
        if getattr(profile, name) != value[name]:
            raise ProfileError(f"profile field {name!r} disagrees with the family")
    return profile


# ---------------------------------------------------------- registered profiles


def _profile(
    *,
    key: str,
    family: PolicyFamily,
    showing: ShowingPolicyId,
    description: str,
    parameters: dict[str, Any] | None = None,
    disabled: tuple[str, ...] = (),
) -> HeuristicProfile:
    return HeuristicProfile.build(
        profile_key=key,
        family=family,
        showing_policy=showing,
        parameters=parameters,
        disabled_rule_ids=disabled,
        description=description,
    )


def registered_profiles() -> dict[str, HeuristicProfile]:
    """Return the finite catalogue of committed Phase 4 profiles."""

    profiles = (
        _profile(
            key="legacy_heuristic_port_v1",
            family=PolicyFamily.LEGACY_HEURISTIC_PORT,
            showing=ShowingPolicyId.LEGACY,
            description=(
                "Deterministic port of the frozen legacy public-information "
                "heuristic, adapted to project_target_v1 showing and scoring."
            ),
        ),
        _profile(
            key="reactive_contract_v1",
            family=PolicyFamily.REACTIVE_CONTRACT,
            showing=ShowingPolicyId.SIMPLE,
            description=(
                "Simple contract-aware baseline with the transparent showing "
                "profile and no public card counting."
            ),
        ),
        _profile(
            key="reactive_contract_legacy_show_v1",
            family=PolicyFamily.REACTIVE_CONTRACT,
            showing=ShowingPolicyId.LEGACY,
            description=(
                "Reactive play with the legacy-derived showing profile; used to "
                "isolate the showing policy in ablation."
            ),
        ),
        _profile(
            key="public_counting_v1",
            family=PolicyFamily.PUBLIC_COUNTING,
            showing=ShowingPolicyId.SIMPLE,
            description=(
                "Reactive baseline extended with hard public inference over voids, "
                "played cards, and certain winners."
            ),
        ),
        _profile(
            key="partner_aware_v1",
            family=PolicyFamily.PARTNER_AWARE,
            showing=ShowingPolicyId.SIMPLE,
            description=(
                "Public-counting baseline extended with explicit partnership rules "
                "and no hidden signalling convention."
            ),
        ),
        _profile(
            key="partner_aware_legacy_convention_v1",
            family=PolicyFamily.PARTNER_AWARE,
            showing=ShowingPolicyId.SIMPLE,
            description=(
                "Partner-aware baseline with the optional legacy showing convention "
                "switched on; used only for convention ablation."
            ),
        ),
        _profile(
            key="match_aware_v1",
            family=PolicyFamily.MATCH_AWARE,
            showing=ShowingPolicyId.SIMPLE,
            description=(
                "Partner-aware baseline extended with deterministic rising-score "
                "rules for showing and play."
            ),
        ),
        _profile(
            key="match_aware_no_match_features_v1",
            family=PolicyFamily.MATCH_AWARE,
            showing=ShowingPolicyId.SIMPLE,
            parameters={"match_state_features_enabled": False},
            description=(
                "Match-aware family with every rising-score rule switched off; the "
                "control variant for the match-state ablation."
            ),
        ),
    )
    catalogue = {profile.profile_key: profile for profile in profiles}
    if len(catalogue) != len(profiles):
        raise ProfileError("registered profiles contain a duplicate key")
    return catalogue


@lru_cache(maxsize=1)
def _registered_cache() -> tuple[tuple[str, HeuristicProfile], ...]:
    """Build the immutable profile catalogue once, after this module is loaded."""

    return tuple(sorted(registered_profiles().items()))


def require_profile(profile_key: str) -> HeuristicProfile:
    for key, profile in _registered_cache():
        if key == profile_key:
            return profile
    raise ProfileError(f"unknown profile key {profile_key!r}")


def profile_catalogue_to_data() -> dict[str, object]:
    return {
        "profiles": [profile.to_data() for _, profile in _registered_cache()],
        "ruleset_id": "project_target_v1",
        "schema_version": "tuppi.agents.profile_catalogue.v1",
    }


# ---------------------------------------------------------------------- helpers


def _validate_parameters(
    family: PolicyFamily, showing_policy: ShowingPolicyId, values: dict[str, Any]
) -> None:
    specs = parameter_specs(family, showing_policy)
    names = {item.name for item in specs}
    actual = set(values)
    if actual != names:
        raise ProfileError(
            "profile parameters differ; "
            f"missing={sorted(names - actual)}, unknown={sorted(actual - names)}"
        )
    for item in specs:
        item.validate(values[item.name])
    if showing_policy is ShowingPolicyId.LEGACY:
        table = float(values["legacy_rami_ev_minimum_table"])
        protected = float(values["legacy_rami_ev_minimum_protected"])
        pressured = float(values["legacy_rami_ev_minimum_pressured"])
        if protected < table:
            raise ProfileError(
                "protecting a large rise cannot lower the RAMI expected-value bar"
            )
        if pressured > table:
            raise ProfileError(
                "gambling for a reset cannot raise the RAMI expected-value bar"
            )
    if FAMILY_SPECS[family].supports_match_state:
        if int(values["match_protect_distance"]) > int(values["match_pressure_distance"]):
            raise ProfileError(
                "the protected distance must not exceed the pressure distance"
            )


def _canonical_text(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: object) -> str:
    import hashlib

    return f"sha256:{hashlib.sha256(_canonical_text(value).encode('utf-8')).hexdigest()}"
