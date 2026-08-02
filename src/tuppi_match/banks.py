"""Fixture-bank roles, and the rules that keep a sealed bank sealed.

A bank is a named family of independent match streams plus the role it may be
used in. The role is not documentation: it is enforced at execution time and
recorded in every resolved manifest.

``development``
    Visible, debuggable, reusable. It may never support a promotion claim.
``calibration``
    Used once to estimate match length, paired variance, leg correlation,
    censoring probability, contract frequencies, and execution cost. It may be
    inspected after execution but must not become a tuning loop.
``promotion_sealed``
    Created only after the agents and the protocol are frozen. The repository
    stores a *commitment*, never the seed material. Opening it is an explicit,
    recorded act.

Sealed-bank design is deliberately simple and local: a seed file kept outside
the repository, a committed commitment digest, and an opening record. There is
no remote evaluation service and no attempt to defend against an operator who
wants to cheat - only against doing it by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import os
from pathlib import Path

from tuppi_eval.serialization import content_digest
from tuppi_engine import atomic_write_canonical_json, strict_json_load_file

from .errors import BankRoleError, SealedBankError
from .streams import MatchStream, stream_family


BANK_SCHEMA_VERSION = "tuppi.match.stream_bank.v1"
SEALED_COMMITMENT_SCHEMA_VERSION = "tuppi.match.sealed_commitment.v1"
SEALED_OPENING_SCHEMA_VERSION = "tuppi.match.sealed_opening.v1"
COMMITMENT_PREFIX_LENGTH = 8
SEALED_SEED_ENVIRONMENT_VARIABLE = "TUPPI_SEALED_SEED_FILE"


class BankRole(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    PROMOTION_SEALED = "promotion_sealed"


PROMOTION_ELIGIBLE_ROLES = frozenset({BankRole.PROMOTION_SEALED})


@dataclass(frozen=True, slots=True)
class StreamBank:
    """An immutable, role-tagged family of independent match streams."""

    bank_id: str
    name: str
    role: BankRole
    root_seed: int | str
    initial_dealer: int
    stream_count: int
    first_stream_index: int
    purpose: str
    schema_version: str = field(default=BANK_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise BankRoleError("bank name must be a nonempty string")
        if not isinstance(self.role, BankRole):
            raise BankRoleError("bank role must be a BankRole value")
        if type(self.stream_count) is not int or self.stream_count <= 0:
            raise BankRoleError("stream_count must be a positive integer")
        if type(self.first_stream_index) is not int or self.first_stream_index < 0:
            raise BankRoleError("first_stream_index must be nonnegative")
        if type(self.initial_dealer) is not int or self.initial_dealer not in range(4):
            raise BankRoleError("initial_dealer must be an integer in 0..3")
        if not isinstance(self.purpose, str) or not self.purpose:
            raise BankRoleError("bank purpose must be a nonempty string")
        if self.bank_id != f"streambank:{content_digest(self.identity_data())}":
            raise BankRoleError("bank_id disagrees with its canonical identity")

    @classmethod
    def build(
        cls,
        *,
        name: str,
        role: BankRole,
        root_seed: int | str,
        initial_dealer: int,
        stream_count: int,
        first_stream_index: int = 0,
        purpose: str,
    ) -> "StreamBank":
        identity = {
            "first_stream_index": first_stream_index,
            "initial_dealer": initial_dealer,
            "name": name,
            "role": role.value,
            "root_seed": root_seed,
            "schema_version": BANK_SCHEMA_VERSION,
            "stream_count": stream_count,
        }
        return cls(
            bank_id=f"streambank:{content_digest(identity)}",
            name=name,
            role=role,
            root_seed=root_seed,
            initial_dealer=initial_dealer,
            stream_count=stream_count,
            first_stream_index=first_stream_index,
            purpose=purpose,
        )

    def identity_data(self) -> dict[str, object]:
        return {
            "first_stream_index": self.first_stream_index,
            "initial_dealer": self.initial_dealer,
            "name": self.name,
            "role": self.role.value,
            "root_seed": self.root_seed,
            "schema_version": BANK_SCHEMA_VERSION,
            "stream_count": self.stream_count,
        }

    @property
    def supports_promotion(self) -> bool:
        return self.role in PROMOTION_ELIGIBLE_ROLES

    def streams(self) -> tuple[MatchStream, ...]:
        return stream_family(
            root_seed=self.root_seed,
            initial_dealer=self.initial_dealer,
            count=self.stream_count,
            first_index=self.first_stream_index,
        )

    def stream(self, offset: int) -> MatchStream:
        if type(offset) is not int or not 0 <= offset < self.stream_count:
            raise BankRoleError(
                f"stream offset {offset!r} is outside bank {self.name!r}"
            )
        return MatchStream.build(
            root_seed=self.root_seed,
            stream_index=self.first_stream_index + offset,
            initial_dealer=self.initial_dealer,
        )

    def commitment(self, *, streams: int | None = None) -> str:
        """Digest the first deals of the first ``streams`` streams.

        A cheap, checkable proof that a later run reads the same fixtures. It
        commits to content, not to storage: no deal is written anywhere.
        """

        limit = self.stream_count if streams is None else streams
        if type(limit) is not int or not 0 < limit <= self.stream_count:
            raise BankRoleError("commitment stream count is out of range")
        return content_digest(
            {
                "bank_id": self.bank_id,
                "prefix_commitments": [
                    self.stream(offset).prefix_commitment(COMMITMENT_PREFIX_LENGTH)
                    for offset in range(limit)
                ],
                "prefix_length": COMMITMENT_PREFIX_LENGTH,
                "schema_version": "tuppi.match.bank_commitment.v1",
                "streams_committed": limit,
            }
        )

    def to_data(self) -> dict[str, object]:
        return {
            **self.identity_data(),
            "bank_id": self.bank_id,
            "purpose": self.purpose,
            "supports_promotion": self.supports_promotion,
        }


def require_role(bank: StreamBank, expected: BankRole) -> StreamBank:
    if bank.role is not expected:
        raise BankRoleError(
            f"bank {bank.name!r} has role {bank.role.value!r}, not {expected.value!r}"
        )
    return bank


def require_not_sealed(bank: StreamBank, *, action: str) -> StreamBank:
    """Refuse ordinary development work on a promotion-sealed bank."""

    if bank.role is BankRole.PROMOTION_SEALED:
        raise SealedBankError(
            f"{action} is not permitted on the promotion-sealed bank "
            f"{bank.name!r}; open it explicitly and record the opening"
        )
    return bank


# ----------------------------------------------------------- sealed bank files


def sealed_commitment(bank: StreamBank, *, streams: int | None = None) -> dict[str, object]:
    """Return the committable record of a sealed bank, without its seed."""

    require_role(bank, BankRole.PROMOTION_SEALED)
    limit = bank.stream_count if streams is None else streams
    return {
        "bank_commitment": bank.commitment(streams=limit),
        "bank_id": bank.bank_id,
        "initial_dealer": bank.initial_dealer,
        "name": bank.name,
        "prefix_length": COMMITMENT_PREFIX_LENGTH,
        "purpose": bank.purpose,
        "role": bank.role.value,
        "schema_version": SEALED_COMMITMENT_SCHEMA_VERSION,
        "seed_location": (
            "outside the repository; supply through the "
            f"{SEALED_SEED_ENVIRONMENT_VARIABLE} environment variable"
        ),
        "stream_count": bank.stream_count,
        "streams_committed": limit,
        "usage_rule": (
            "Opening this bank is an explicit recorded act. It must not be used "
            "for candidate development, debugging, or repeated measurement."
        ),
    }


def write_sealed_seed(path: str | Path, *, seed: str) -> dict[str, object]:
    """Write the sealed seed material outside the repository."""

    if not isinstance(seed, str) or len(seed) < 16:
        raise SealedBankError("a sealed seed must be a string of at least 16 characters")
    target = Path(path)
    if _inside_repository(target):
        raise SealedBankError(
            "sealed seed material must not be written inside the repository"
        )
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "tuppi.match.sealed_seed.v1",
        "seed": seed,
        "seed_digest": content_digest({"seed": seed}),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_canonical_json(target, payload)
    return {"path": str(target), "seed_digest": payload["seed_digest"]}


def open_sealed_bank(
    *,
    name: str,
    stream_count: int,
    initial_dealer: int,
    purpose: str,
    reason: str,
    seed_path: str | Path | None = None,
) -> tuple[StreamBank, dict[str, object]]:
    """Open the sealed bank, returning it together with an opening record.

    The seed never enters the repository. It is read from ``seed_path`` or from
    the path named by ``TUPPI_SEALED_SEED_FILE``. Opening always produces a
    record so that an opening cannot happen silently.
    """

    if not isinstance(reason, str) or len(reason) < 8:
        raise SealedBankError("opening a sealed bank requires an explicit reason")
    location = seed_path or os.environ.get(SEALED_SEED_ENVIRONMENT_VARIABLE)
    if not location:
        raise SealedBankError(
            "no sealed seed available; set "
            f"{SEALED_SEED_ENVIRONMENT_VARIABLE} or pass seed_path"
        )
    target = Path(location)
    if _inside_repository(target):
        raise SealedBankError("sealed seed material must live outside the repository")
    payload = strict_json_load_file(target)
    if type(payload) is not dict or "seed" not in payload:
        raise SealedBankError("sealed seed file is malformed")
    seed = payload["seed"]
    if not isinstance(seed, str) or not seed:
        raise SealedBankError("sealed seed must be a nonempty string")
    bank = StreamBank.build(
        name=name,
        role=BankRole.PROMOTION_SEALED,
        root_seed=seed,
        initial_dealer=initial_dealer,
        stream_count=stream_count,
        purpose=purpose,
    )
    record = {
        "bank_commitment": bank.commitment(),
        "bank_id": bank.bank_id,
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "schema_version": SEALED_OPENING_SCHEMA_VERSION,
        "seed_digest": content_digest({"seed": seed}),
        "seed_source": str(target),
    }
    return bank, record


def _inside_repository(path: Path) -> bool:
    """Whether ``path`` lies inside any version-controlled working tree.

    The test must not be "is this under the directory the *module* happens to
    live in": once the package is installed to site-packages that infers the
    wrong root and the guard silently stops protecting anything. Instead walk up
    from the target itself and look for a repository marker, which is exactly
    what "must not be committed" means and works from source or from an install.
    """

    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError:  # pragma: no cover - unresolvable paths are not repositories
        return False
    for ancestor in (resolved, *resolved.parents):
        for marker in (".git", ".hg", ".svn"):
            if (ancestor / marker).exists():
                return True
    return False
