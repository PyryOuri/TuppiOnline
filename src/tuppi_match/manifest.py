"""Resolved immutable manifests for complete-match experiments.

A manifest fixes everything that can change a semantic result: the bank and its
role, the stream generator, the comparisons, the safety cap *and the reason it
was chosen*, the starting score, and the analysis parameters. It fixes nothing
that cannot: no output path, no timestamp, no worker count, no machine name.

The comparison identity deliberately excludes the pair count. A complete-match
bank is extensible, so adding pairs must extend an experiment rather than
invalidate every record already written under it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tuppi_eval.serialization import canonical_json_text, content_digest
from tuppi_rules import MATCH_TARGET, MatchScore

from .banks import BankRole, StreamBank
from .errors import ManifestError
from .streams import STREAM_GENERATOR_ID, STREAM_PROTOCOL_VERSION


MATCH_MANIFEST_SCHEMA_VERSION = "tuppi.match.manifest.v1"
MATCH_COMPARISON_SCHEMA_VERSION = "tuppi.match.comparison.v1"
MATCH_PROTOCOL_VERSION = "tuppi.match.complete_duplicate_pair.v1"
STATISTICS_VERSION = "tuppi.match.pair_inference.v1"

#: Development default. Chosen from the calibration match-length distribution,
#: not guessed: see ``docs/match/complete_match_protocol.md``. The Phase 4 value
#: of 40 sat near the *median* observed length, which is why it censored a third
#: of all pairs.
DEFAULT_SAFETY_CAP = 512
DEFAULT_SAFETY_CAP_REASON = (
    "Infrastructure safeguard only. Calibrated far above the observed p99 match "
    "length so that censoring is exceptional rather than routine."
)


@dataclass(frozen=True, slots=True)
class MatchComparison:
    """One candidate-versus-opponent complete-match comparison."""

    comparison_id: str
    name: str
    candidate_profile_key: str
    opponent_profile_key: str
    candidate_agent_id: str
    opponent_agent_id: str
    starting_score: tuple[int, int]
    result_class: str
    hypothesis: str
    schema_version: str = field(
        default=MATCH_COMPARISON_SCHEMA_VERSION, init=False
    )

    def __post_init__(self) -> None:
        for label, value in (
            ("name", self.name),
            ("candidate_profile_key", self.candidate_profile_key),
            ("opponent_profile_key", self.opponent_profile_key),
            ("hypothesis", self.hypothesis),
        ):
            if not isinstance(value, str) or not value:
                raise ManifestError(f"{label} must be a nonempty string")
        for label, value in (
            ("candidate_agent_id", self.candidate_agent_id),
            ("opponent_agent_id", self.opponent_agent_id),
        ):
            if not isinstance(value, str) or not value.startswith("agent:sha256:"):
                raise ManifestError(f"{label} must be a canonical agent identity")
        if self.candidate_agent_id == self.opponent_agent_id:
            raise ManifestError(
                "a comparison needs two distinct agents; a self-comparison "
                "measures the duplicate design, not a policy"
            )
        if self.result_class not in ("calibration", "development", "ablation", "sealed"):
            raise ManifestError(f"unknown result class {self.result_class!r}")
        if len(self.starting_score) != 2:
            raise ManifestError("starting_score must be a pair")
        try:
            score = MatchScore(*self.starting_score)
        except Exception as exc:  # pragma: no cover - MatchScore validates
            raise ManifestError(f"invalid starting score: {exc}") from exc
        if max(score.as_tuple()) >= MATCH_TARGET:
            raise ManifestError("a match cannot start from a terminal score")
        if self.comparison_id != f"cmp:{content_digest(self.identity_data())}":
            raise ManifestError("comparison_id disagrees with its identity")

    @classmethod
    def build(
        cls,
        *,
        name: str,
        candidate_profile_key: str,
        opponent_profile_key: str,
        candidate_agent_id: str,
        opponent_agent_id: str,
        result_class: str,
        hypothesis: str,
        starting_score: tuple[int, int] = (0, 0),
    ) -> "MatchComparison":
        values = {
            "name": name,
            "candidate_profile_key": candidate_profile_key,
            "opponent_profile_key": opponent_profile_key,
            "candidate_agent_id": candidate_agent_id,
            "opponent_agent_id": opponent_agent_id,
            "starting_score": tuple(starting_score),
            "result_class": result_class,
            "hypothesis": hypothesis,
        }
        provisional = object.__new__(cls)
        for key, value in values.items():
            object.__setattr__(provisional, key, value)
        object.__setattr__(
            provisional, "schema_version", MATCH_COMPARISON_SCHEMA_VERSION
        )
        return cls(
            comparison_id=f"cmp:{content_digest(provisional.identity_data())}",
            **values,
        )

    def identity_data(self) -> dict[str, object]:
        """Identity excludes the pair count so that a bank stays extensible."""

        return {
            "candidate_agent_id": self.candidate_agent_id,
            "match_protocol_version": MATCH_PROTOCOL_VERSION,
            "opponent_agent_id": self.opponent_agent_id,
            "schema_version": MATCH_COMPARISON_SCHEMA_VERSION,
            "starting_score": list(self.starting_score),
        }

    def to_data(self) -> dict[str, object]:
        return {
            **self.identity_data(),
            "candidate_profile_key": self.candidate_profile_key,
            "comparison_id": self.comparison_id,
            "hypothesis": self.hypothesis,
            "name": self.name,
            "opponent_profile_key": self.opponent_profile_key,
            "result_class": self.result_class,
        }


@dataclass(frozen=True, slots=True)
class MatchManifest:
    """Everything a complete-match experiment needs, and nothing operational."""

    manifest_id: str
    name: str
    bank: StreamBank
    bank_commitment: str
    comparisons: tuple[MatchComparison, ...]
    pair_count: int
    safety_cap: int
    safety_cap_reason: str
    confidence_level: float
    bootstrap_replicates: int
    sign_flip_replicates: int
    analysis_seed: int | str
    engine_identity: str
    agents_version: str
    software_environment_json: str
    schema_version: str = field(default=MATCH_MANIFEST_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bank, StreamBank):
            raise ManifestError("manifest requires a StreamBank")
        if type(self.comparisons) is not tuple or not self.comparisons:
            raise ManifestError("a manifest needs at least one comparison")
        identifiers = [item.comparison_id for item in self.comparisons]
        if len(set(identifiers)) != len(identifiers):
            raise ManifestError("a manifest cannot repeat a comparison")
        if type(self.pair_count) is not int or self.pair_count <= 0:
            raise ManifestError("pair_count must be a positive integer")
        if self.pair_count > self.bank.stream_count:
            raise ManifestError(
                f"the bank supplies {self.bank.stream_count} streams but the "
                f"manifest requests {self.pair_count} pairs"
            )
        if type(self.safety_cap) is not int or self.safety_cap <= 0:
            raise ManifestError("safety_cap must be a positive integer")
        if not isinstance(self.safety_cap_reason, str) or len(
            self.safety_cap_reason
        ) < 20:
            raise ManifestError(
                "the safety cap must carry an explicit reason in the manifest"
            )
        if not 0.5 < self.confidence_level < 1.0:
            raise ManifestError("confidence_level must lie in (0.5, 1)")
        for label, value in (
            ("bootstrap_replicates", self.bootstrap_replicates),
            ("sign_flip_replicates", self.sign_flip_replicates),
        ):
            if type(value) is not int or value <= 0:
                raise ManifestError(f"{label} must be a positive integer")
        if self.bank_commitment != self.bank.commitment(
            streams=min(self.pair_count, self.bank.stream_count)
        ):
            raise ManifestError("bank commitment disagrees with the resolved bank")
        if self.manifest_id != f"matchmanifest:{content_digest(self.identity_data())}":
            raise ManifestError("manifest_id disagrees with its canonical identity")

    @classmethod
    def build(
        cls,
        *,
        name: str,
        bank: StreamBank,
        comparisons: tuple[MatchComparison, ...],
        pair_count: int,
        engine_identity: str,
        agents_version: str,
        safety_cap: int = DEFAULT_SAFETY_CAP,
        safety_cap_reason: str = DEFAULT_SAFETY_CAP_REASON,
        confidence_level: float = 0.95,
        bootstrap_replicates: int = 10_000,
        sign_flip_replicates: int = 10_000,
        analysis_seed: int | str = "tuppi-match-analysis-v1",
        software_environment: dict[str, Any] | None = None,
    ) -> "MatchManifest":
        ordered = tuple(
            sorted(comparisons, key=lambda item: item.comparison_id)
        )
        values = {
            "name": name,
            "bank": bank,
            "bank_commitment": bank.commitment(
                streams=min(pair_count, bank.stream_count)
            ),
            "comparisons": ordered,
            "pair_count": pair_count,
            "safety_cap": safety_cap,
            "safety_cap_reason": safety_cap_reason,
            "confidence_level": confidence_level,
            "bootstrap_replicates": bootstrap_replicates,
            "sign_flip_replicates": sign_flip_replicates,
            "analysis_seed": analysis_seed,
            "engine_identity": engine_identity,
            "agents_version": agents_version,
            "software_environment_json": canonical_json_text(
                software_environment or {}
            ),
        }
        provisional = object.__new__(cls)
        for key, value in values.items():
            object.__setattr__(provisional, key, value)
        object.__setattr__(provisional, "schema_version", MATCH_MANIFEST_SCHEMA_VERSION)
        return cls(
            manifest_id=f"matchmanifest:{content_digest(provisional.identity_data())}",
            **values,
        )

    @property
    def role(self) -> BankRole:
        return self.bank.role

    @property
    def supports_promotion(self) -> bool:
        return self.bank.supports_promotion

    def identity_data(self) -> dict[str, object]:
        return {
            "agents_version": self.agents_version,
            "analysis_seed": self.analysis_seed,
            "bank": self.bank.identity_data(),
            "bank_commitment": self.bank_commitment,
            "bootstrap_replicates": self.bootstrap_replicates,
            "comparisons": [item.identity_data() for item in self.comparisons],
            "confidence_level": self.confidence_level,
            "engine_identity": self.engine_identity,
            "match_protocol_version": MATCH_PROTOCOL_VERSION,
            "name": self.name,
            "pair_count": self.pair_count,
            "safety_cap": self.safety_cap,
            "schema_version": MATCH_MANIFEST_SCHEMA_VERSION,
            "sign_flip_replicates": self.sign_flip_replicates,
            "statistics_version": STATISTICS_VERSION,
            "stream_generator_id": STREAM_GENERATOR_ID,
            "stream_protocol_version": STREAM_PROTOCOL_VERSION,
        }

    def to_data(self) -> dict[str, object]:
        import json

        return {
            **self.identity_data(),
            "bank_detail": self.bank.to_data(),
            "bank_role": self.role.value,
            "comparison_detail": [item.to_data() for item in self.comparisons],
            "manifest_id": self.manifest_id,
            "safety_cap_reason": self.safety_cap_reason,
            "software_environment": json.loads(self.software_environment_json),
            "supports_promotion": self.supports_promotion,
        }
