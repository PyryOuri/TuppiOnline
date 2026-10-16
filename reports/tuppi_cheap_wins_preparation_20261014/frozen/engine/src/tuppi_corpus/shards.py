"""Shard files and the append-only catalogue.

A **shard is a stream range**, which is what makes a run resumable and each
piece of it independently citable: one worker owns one shard, writes it, fsyncs
it, and only then appends ``(path, digest, counts)`` to the catalogue.  A crash
leaves an uncatalogued file, which is discarded and regenerated rather than
half-trusted.

The canonical format is a framed, compressed binary block with **no third-party
dependency**: ``compression.zstd`` arrived in the 3.14 standard library, and
where it is absent the codec falls back to ``zlib`` and records which was used.
That keeps ``dependencies = []`` true for the package, and keeps Parquet where
it belongs - an *export* for querying, not the thing being trusted.

The digest covers the **uncompressed** payload, so a shard rebuilt with a
different codec, compression level, or zstd version still verifies.  A digest
over the compressed bytes would have made the recipe depend on the compressor.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct

from .errors import CorpusFormatError, CorpusIntegrityError
from .records import DEAL_ROW_BYTES, MATCH_ROW_BYTES, DealRecord, MatchRecord


SHARD_SCHEMA_VERSION = "tuppi.corpus.shard.v1"
CATALOG_SCHEMA_VERSION = "tuppi.corpus.catalog.v1"

_MAGIC = b"TDCS"
_FORMAT_VERSION = 1

CODEC_ZSTD = 1
CODEC_ZLIB = 2

_HEADER = struct.Struct("<4sBBHIIIII32s32s")
HEADER_BYTES = _HEADER.size


def _zstd():
    try:
        from compression import zstd  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - depends on the interpreter
        return None
    return zstd


def compress(payload: bytes) -> tuple[int, bytes]:
    module = _zstd()
    if module is not None:
        return (CODEC_ZSTD, module.compress(payload, level=10))
    import zlib

    return (CODEC_ZLIB, zlib.compress(payload, 6))


def decompress(codec: int, payload: bytes) -> bytes:
    """Decompress, reporting damage as a corpus error rather than a codec one.

    A truncated or flipped byte reaches the decompressor before it reaches the
    digest check, so without this wrapper a corrupt shard surfaces as a
    ``ZstdError`` and a caller cannot tell shard damage from a bug.
    """

    if codec == CODEC_ZSTD:
        module = _zstd()
        if module is None:
            raise CorpusFormatError(
                "shard is zstd-compressed but this interpreter has no zstd; "
                "read it on Python 3.14 or later"
            )
        try:
            return module.decompress(payload)
        except Exception as exc:  # noqa: BLE001 - codec exceptions vary by build
            raise CorpusIntegrityError(f"shard body is not valid zstd: {exc}") from exc
    if codec == CODEC_ZLIB:
        import zlib

        try:
            return zlib.decompress(payload)
        except zlib.error as exc:
            raise CorpusIntegrityError(f"shard body is not valid zlib: {exc}") from exc
    raise CorpusFormatError(f"unknown shard codec {codec}")


@dataclass(frozen=True, slots=True)
class ShardHeader:
    stream_start: int
    stream_stop: int
    match_count: int
    deal_count: int
    payload_digest: str
    run_digest: str
    codec: int


def _digest_bytes(hex_digest: str) -> bytes:
    text = hex_digest.removeprefix("run:").removeprefix("sha256:")
    if len(text) != 64:
        raise CorpusFormatError("expected a 64-character hex digest")
    return bytes.fromhex(text)


def shard_name(stream_start: int, stream_stop: int) -> str:
    return f"part-{stream_start:09d}-{stream_stop:09d}.tdc"


def write_shard(
    path: Path,
    *,
    run_id: str,
    stream_start: int,
    stream_stop: int,
    matches: tuple[MatchRecord, ...],
    deals: tuple[DealRecord, ...],
) -> str:
    """Write one shard atomically and return the payload digest.

    Written to a temporary name, fsynced, then renamed, so a reader never sees a
    partial shard and a crash cannot leave a plausible-looking one.
    """

    payload = b"".join(
        [record.to_bytes() for record in matches] + [row.to_bytes() for row in deals]
    )
    digest = hashlib.sha256(payload).hexdigest()
    codec, body = compress(payload)
    header = _HEADER.pack(
        _MAGIC,
        _FORMAT_VERSION,
        codec,
        0,
        stream_start,
        stream_stop,
        len(matches),
        len(deals),
        len(body),
        bytes.fromhex(digest),
        _digest_bytes(run_id),
    )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".partial")
    with open(temporary, "wb") as handle:
        handle.write(header)
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    return f"sha256:{digest}"


def read_shard(path: Path) -> tuple[ShardHeader, tuple[MatchRecord, ...], tuple[DealRecord, ...]]:
    """Read one shard, verifying the payload digest before decoding rows."""

    raw = Path(path).read_bytes()
    if len(raw) < HEADER_BYTES:
        raise CorpusFormatError("shard is shorter than its header")
    (
        magic,
        version,
        codec,
        _reserved,
        stream_start,
        stream_stop,
        match_count,
        deal_count,
        body_length,
        payload_digest,
        run_digest,
    ) = _HEADER.unpack(raw[:HEADER_BYTES])
    if magic != _MAGIC:
        raise CorpusFormatError("not a corpus shard")
    if version != _FORMAT_VERSION:
        raise CorpusFormatError(f"unsupported shard format version {version}")
    body = raw[HEADER_BYTES : HEADER_BYTES + body_length]
    if len(body) != body_length:
        raise CorpusFormatError("shard body is truncated")
    payload = decompress(codec, body)
    if hashlib.sha256(payload).digest() != payload_digest:
        raise CorpusIntegrityError(f"shard payload digest mismatch: {path}")
    expected = match_count * MATCH_ROW_BYTES + deal_count * DEAL_ROW_BYTES
    if len(payload) != expected:
        raise CorpusFormatError("shard payload length disagrees with its row counts")
    matches = tuple(
        MatchRecord.from_bytes(payload[offset : offset + MATCH_ROW_BYTES])
        for offset in range(0, match_count * MATCH_ROW_BYTES, MATCH_ROW_BYTES)
    )
    base = match_count * MATCH_ROW_BYTES
    deals = tuple(
        DealRecord.from_bytes(payload[offset : offset + DEAL_ROW_BYTES])
        for offset in range(base, base + deal_count * DEAL_ROW_BYTES, DEAL_ROW_BYTES)
    )
    header = ShardHeader(
        stream_start=stream_start,
        stream_stop=stream_stop,
        match_count=match_count,
        deal_count=deal_count,
        payload_digest=f"sha256:{payload_digest.hex()}",
        run_digest=f"run:sha256:{run_digest.hex()}",
        codec=codec,
    )
    return (header, matches, deals)


# ------------------------------------------------------------------ catalogue


def catalog_path(run_directory: Path) -> Path:
    return Path(run_directory) / "catalog.jsonl"


def append_catalog_entry(run_directory: Path, entry: dict[str, object]) -> None:
    """Append one completed shard.  Line-oriented so a crash truncates cleanly."""

    required = {"deals", "digest", "matches", "shard", "stream_start", "stream_stop"}
    if not required <= set(entry):
        raise CorpusFormatError(f"catalogue entry needs {sorted(required)}")
    path = catalog_path(run_directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def read_catalog(run_directory: Path) -> tuple[dict[str, object], ...]:
    """Every completed shard.  A trailing partial line is ignored, not fatal."""

    path = catalog_path(run_directory)
    if not path.exists():
        return ()
    entries: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            break
    return tuple(entries)


def completed_shards(run_directory: Path) -> frozenset[tuple[int, int]]:
    """The stream ranges already catalogued, so a run can resume."""

    return frozenset(
        (int(entry["stream_start"]), int(entry["stream_stop"]))
        for entry in read_catalog(run_directory)
    )


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "CODEC_ZLIB",
    "CODEC_ZSTD",
    "HEADER_BYTES",
    "SHARD_SCHEMA_VERSION",
    "ShardHeader",
    "append_catalog_entry",
    "catalog_path",
    "completed_shards",
    "compress",
    "decompress",
    "read_catalog",
    "read_shard",
    "shard_name",
    "write_shard",
]
