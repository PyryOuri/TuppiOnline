"""Frozen-baseline integrity: prove nothing moved before measuring anything.

Phase 5B adds capabilities the earlier phases explicitly disclaimed - an exact
solver, a hidden-hand sampler, a constraint model. That is precisely the
situation in which a frozen baseline is easiest to spoil, and hardest to notice:
a helper quietly imported into an agent, a threshold nudged while debugging, a
report regenerated with a newer profile. Policy alone does not catch any of that.

So the gate is mechanical, and it checks five different things:

1. **Archive artifacts.** The two frozen legacy files still hash to the values in
   ``manifests/legacy_v9.json``. No recorded baseline is needed for this one: the
   manifest is itself the record.
2. **Ruleset content.** ``configs/rules/project_target_v1.json`` and the executable
   reference's identifiers still digest to the recorded values.
3. **Phase 4 agents.** The behaviour digests in
   ``reports/phase5a/phase4_frozen_agents.json`` still reproduce, via the Phase 5A
   snapshot verifier rather than a second implementation of it.
4. **Phase 5A artifacts.** The committed reports, and the sealed-bank commitment,
   still hash to the recorded values, and no sealed-open record exists.
5. **Capability containment.** Every frozen agent still declares
   ``search``, ``belief_model``, ``endgame_solver``, ``hidden_hand_sampling``,
   ``learning``, and ``rollout_budget`` as null, and no earlier package imports
   :mod:`tuppi_exact`. The Phase 5B layer is one-directional by construction: it
   reads Phase 4, and Phase 4 cannot reach it.

Check 5 is the one that only Phase 5B needs, and it is the reason this module
exists rather than reusing ``tuppi-match freeze --verify`` alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

from tuppi_engine import strict_json_load_file
from tuppi_eval.serialization import content_digest
from tuppi_rules import RULESET_ID, RULESET_VERSION

from .errors import IntegrityError


BASELINE_SCHEMA_VERSION = "tuppi.exact.frozen_baseline.v1"

#: Files whose bytes must not change while Phase 5B runs.
FROZEN_ARTIFACT_PATHS: tuple[str, ...] = (
    "Archive/tuppi_emulator_v9.py",
    "Archive/tuppi_gui_client_multi_v8.py",
    "configs/rules/project_target_v1.json",
    "manifests/legacy_v9.json",
    "reports/phase4/baseline_report.json",
    "reports/phase5a/calibration_report.json",
    "reports/phase5a/match_length_calibration.json",
    "reports/phase5a/phase4_frozen_agents.json",
    "reports/phase5a/score_state_diagnostics.json",
    "reports/phase5a/sealed_commitment.json",
)

#: Capability fields that must stay null on every frozen Phase 4 agent.
DISCLAIMED_CAPABILITY_FIELDS: tuple[str, ...] = (
    "belief_model",
    "endgame_solver",
    "hidden_hand_sampling",
    "learning",
    "rollout_budget",
    "search",
)

#: Packages that existed before Phase 5B and must not depend on it.
EARLIER_PACKAGES: tuple[str, ...] = (
    "tuppi_rules",
    "tuppi_engine",
    "tuppi_eval",
    "tuppi_agents",
    "tuppi_legacy",
    "tuppi_match",
)

#: Directory names that indicate a cloud-synced working tree. Phase 5A recorded a
#: reproducible stall in a subprocess test under iCloud; the relocation to a plain
#: local path is what fixed it, so the location is worth reporting.
CLOUD_SYNCED_MARKERS: tuple[str, ...] = (
    "Documents",
    "Library/Mobile Documents",
    "iCloud Drive",
    "Dropbox",
    "Google Drive",
    "OneDrive",
)


def repository_root(explicit: str | Path | None = None) -> Path:
    """Locate the repository root, or raise.

    With an editable install the package lives inside the working tree, so the
    root is two levels above this file. An explicit path always wins, which is
    what lets a test point the checks at a fixture tree.
    """

    if explicit is not None:
        root = Path(explicit).resolve()
    else:
        root = Path(__file__).resolve().parents[2]
    for required in ("pyproject.toml", "manifests/legacy_v9.json"):
        if not (root / required).is_file():
            raise IntegrityError(
                f"{root} does not look like the Tuppi repository: {required} is missing"
            )
    return root


def file_digest(path: Path) -> str:
    """Return the canonical ``sha256:`` digest of a file's exact bytes."""

    if not path.is_file():
        raise IntegrityError(f"cannot digest missing file {path}")
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def archive_manifest_agreement(root: Path) -> list[str]:
    """Return drift descriptions for Archive files against their own manifest."""

    manifest = strict_json_load_file(str(root / "manifests" / "legacy_v9.json"))
    problems: list[str] = []
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or not artifacts:
        raise IntegrityError("the legacy manifest lists no artifacts")
    for entry in artifacts:
        path = root / str(entry["path"])
        if not path.is_file():
            problems.append(f"{entry['path']}: frozen artifact is missing")
            continue
        payload = path.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != entry["sha256"]:
            problems.append(
                f"{entry['path']}: sha256 changed from {entry['sha256']} to {actual}"
            )
        if len(payload) != int(entry["size_bytes"]):
            problems.append(
                f"{entry['path']}: size changed from {entry['size_bytes']} to "
                f"{len(payload)}"
            )
    return problems


def capability_containment(root: Path) -> list[str]:
    """Return drift descriptions for the Phase 5B capability boundary."""

    from tuppi_match.freeze import build_snapshot

    problems: list[str] = []
    snapshot = build_snapshot()
    for agent in snapshot["agents"]:
        for field_name in DISCLAIMED_CAPABILITY_FIELDS:
            if agent.get(field_name) is not None:
                problems.append(
                    f"{agent['profile_key']}: {field_name} is no longer null, so a "
                    "Phase 5B capability has leaked into a frozen agent identity"
                )
    for package in EARLIER_PACKAGES:
        directory = root / "src" / package
        if not directory.is_dir():
            problems.append(f"src/{package} is missing")
            continue
        for module in sorted(directory.glob("*.py")):
            if "tuppi_exact" in module.read_text(encoding="utf-8"):
                problems.append(
                    f"src/{package}/{module.name} references tuppi_exact; the "
                    "Phase 5B layer must stay one-directional"
                )
    return problems


def sealed_bank_containment(root: Path) -> list[str]:
    """Return drift descriptions for the still-sealed promotion bank."""

    problems: list[str] = []
    commitment_path = root / "reports" / "phase5a" / "sealed_commitment.json"
    commitment = strict_json_load_file(str(commitment_path))
    if commitment.get("role") != "promotion_sealed":
        problems.append("the sealed commitment no longer declares a sealed role")
    for required in ("bank_commitment", "bank_id", "seed_digest", "usage_rule"):
        if not commitment.get(required):
            problems.append(f"the sealed commitment lost its {required} field")
    opened = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "reports").rglob("*.json")
        if "sealed_open" in path.name or "sealed_opening" in path.name
    )
    if opened:
        problems.append(
            "a sealed-bank opening record is committed: " + ", ".join(opened)
        )
    return problems


@dataclass(frozen=True, slots=True)
class FrozenBaselineSnapshot:
    """Every digest Phase 5B commits to leaving alone."""

    artifact_digests: tuple[tuple[str, str], ...]
    ruleset_id: str
    ruleset_version: str
    ruleset_config_digest: str
    phase4_snapshot_digest: str
    phase4_behaviour_digests: tuple[tuple[str, str], ...]
    schema_version: str = field(default=BASELINE_SCHEMA_VERSION, init=False)

    def to_data(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "artifact_digests": [
                {"digest": digest, "path": path}
                for path, digest in self.artifact_digests
            ],
            "phase4_behaviour_digests": [
                {"behaviour_digest": digest, "profile_key": key}
                for key, digest in self.phase4_behaviour_digests
            ],
            "phase4_snapshot_digest": self.phase4_snapshot_digest,
            "purpose": (
                "Phase 5B integrity baseline. Every value here is expected to be "
                "reproduced exactly; any difference is drift, not an update."
            ),
            "ruleset_config_digest": self.ruleset_config_digest,
            "ruleset_id": self.ruleset_id,
            "ruleset_version": self.ruleset_version,
            "schema_version": BASELINE_SCHEMA_VERSION,
        }
        payload["baseline_digest"] = content_digest(payload)
        return payload


def build_baseline(root: str | Path | None = None) -> dict[str, object]:
    """Build the current frozen-baseline snapshot."""

    from tuppi_match.freeze import build_snapshot

    resolved = repository_root(root)
    snapshot = build_snapshot()
    return FrozenBaselineSnapshot(
        artifact_digests=tuple(
            (path, file_digest(resolved / path)) for path in FROZEN_ARTIFACT_PATHS
        ),
        ruleset_id=RULESET_ID,
        ruleset_version=RULESET_VERSION,
        ruleset_config_digest=content_digest(
            strict_json_load_file(
                str(resolved / "configs" / "rules" / "project_target_v1.json")
            )
        ),
        phase4_snapshot_digest=str(snapshot["snapshot_digest"]),
        phase4_behaviour_digests=tuple(
            (str(agent["profile_key"]), str(agent["behaviour_digest"]))
            for agent in snapshot["agents"]
        ),
    ).to_data()


def verify_baseline(
    recorded: dict[str, object], root: str | Path | None = None
) -> list[str]:
    """Return every drift description; an empty list means nothing moved.

    The recorded baseline covers checks 2 to 4. Checks 1 and 5 need no recorded
    values because the repository carries its own reference for them, so they run
    unconditionally and are the ones that still work on a fresh clone.
    """

    if type(recorded) is not dict:
        raise IntegrityError("a recorded baseline must be a JSON object")
    if recorded.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise IntegrityError("unsupported frozen-baseline schema_version")
    resolved = repository_root(root)

    problems: list[str] = []
    problems.extend(archive_manifest_agreement(resolved))
    problems.extend(capability_containment(resolved))
    problems.extend(sealed_bank_containment(resolved))

    from tuppi_match.freeze import verify_snapshot

    problems.extend(
        verify_snapshot(
            strict_json_load_file(
                str(resolved / "reports" / "phase5a" / "phase4_frozen_agents.json")
            )
        )
    )

    current = build_baseline(resolved)
    for key in (
        "phase4_snapshot_digest",
        "ruleset_config_digest",
        "ruleset_id",
        "ruleset_version",
    ):
        if current[key] != recorded.get(key):
            problems.append(
                f"{key} changed from {recorded.get(key)!r} to {current[key]!r}"
            )
    recorded_files = {
        str(item["path"]): str(item["digest"])
        for item in recorded.get("artifact_digests", [])  # type: ignore[union-attr]
    }
    current_files = {
        str(item["path"]): str(item["digest"])
        for item in current["artifact_digests"]  # type: ignore[index]
    }
    for path in sorted(set(recorded_files) | set(current_files)):
        if recorded_files.get(path) != current_files.get(path):
            problems.append(
                f"{path}: digest changed from {recorded_files.get(path)} to "
                f"{current_files.get(path)}"
            )
    recorded_behaviour = {
        str(item["profile_key"]): str(item["behaviour_digest"])
        for item in recorded.get("phase4_behaviour_digests", [])  # type: ignore[union-attr]
    }
    current_behaviour = {
        str(item["profile_key"]): str(item["behaviour_digest"])
        for item in current["phase4_behaviour_digests"]  # type: ignore[index]
    }
    for key in sorted(set(recorded_behaviour) | set(current_behaviour)):
        if recorded_behaviour.get(key) != current_behaviour.get(key):
            problems.append(
                f"{key}: behaviour digest changed from "
                f"{recorded_behaviour.get(key)} to {current_behaviour.get(key)}"
            )
    return problems


def working_tree_location(root: str | Path | None = None) -> dict[str, object]:
    """Describe where the working tree lives, and whether that is a hazard.

    This is environmental, not baseline content: it is reported, never digested,
    so a committed baseline stays machine-independent.
    """

    resolved = repository_root(root)
    text = resolved.as_posix()
    matches = tuple(
        marker for marker in CLOUD_SYNCED_MARKERS if f"/{marker}/" in f"{text}/"
    )
    return {
        "cloud_synced_markers": list(matches),
        "is_probably_cloud_synced": bool(matches),
        "note": (
            "High-volume benchmark output and subprocess-heavy tests belong on a "
            "plain local filesystem. A cloud-synced working tree was the "
            "reproducible cause of a stalled CLI subprocess test."
        ),
        "repository_root": text,
        "schema_version": "tuppi.exact.working_tree_location.v1",
    }


def integrity_report(root: str | Path | None = None) -> dict[str, object]:
    """Run every check that needs no recorded baseline and report the result."""

    resolved = repository_root(root)
    archive = archive_manifest_agreement(resolved)
    capability = capability_containment(resolved)
    sealed = sealed_bank_containment(resolved)
    return {
        "archive_manifest_problems": archive,
        "baseline": build_baseline(resolved),
        "capability_containment_problems": capability,
        "holds": not (archive or capability or sealed),
        "schema_version": "tuppi.exact.integrity_report.v1",
        "sealed_bank_problems": sealed,
        "working_tree": working_tree_location(resolved),
    }
