"""Checked paired differences from completed duplicate-deal results; no game/model imports."""

from __future__ import annotations

import argparse
import math
import statistics
from pathlib import Path

from .experiment_io import canonical, read_json, write_json

RESULT_SCHEMA = "tuppi.duplicate_eval.v2"
CONTEXT_SCHEMA = "tuppi.frozen_eval_context.v2"
SHARED_CONTEXT = ("schema", "inputs_sha256", "workers", "design", "chunksize", "controller_state")
META = ("seed", "ruleset", "scores", "opponent")


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def validate_result(result: dict, *, allow_legacy: bool = False) -> dict:
    if not isinstance(result, dict):
        raise ValueError("result must be an object")
    for key in (*META, "candidate"):
        if not isinstance(result.get(key), str) or not result[key]:
            raise ValueError(f"result lacks {key}")
    if result["ruleset"] not in ("project_target_v1", "project_target_v2", "project_target_v3"):
        raise ValueError("unknown ruleset")
    if result["scores"] not in ("zero", "uniform"):
        raise ValueError("unknown starting-score design")
    n = result.get("base_deals")
    if type(n) is not int or n < 2 or not isinstance(result.get("values"), list) or len(result["values"]) != n:
        raise ValueError("at least two complete base-deal values with matching base_deals are required")
    values = [_number(v, "equity value") for v in result["values"]]
    if any(abs(v) > 1 for v in values):
        raise ValueError("equity changes must be between -1 and 1")
    records = result.get("deal_records")
    if records is not None:
        if result.get("schema") != RESULT_SCHEMA or not isinstance(records, list) or len(records) != n:
            raise ValueError("wrong result schema or incomplete deal records")
        seen, indices = set(), set()
        for i, row in enumerate(records):
            if not isinstance(row, dict):
                raise ValueError("deal record must be an object")
            identity = row.get("deal_id")
            if not isinstance(identity, str) or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
                raise ValueError("invalid deal identity")
            index = row.get("index")
            if identity in seen or type(index) is not int or index in indices or not 0 <= index < n:
                raise ValueError("duplicate/missing deal identity or index")
            seen.add(identity)
            indices.add(index)
            score = row.get("score")
            if not isinstance(score, list) or len(score) != 2 or any(type(v) is not int or v not in range(0, 49, 4) for v in score):
                raise ValueError("invalid starting score")
            if sum(v > 0 for v in score) > 1 or (result["scores"] == "zero" and score != [0, 0]):
                raise ValueError("starting score contradicts score design")
            if _number(row.get("value"), "record value") != values[i]:
                raise ValueError("deal record and value array disagree")
    elif not allow_legacy or result.get("schema") is not None:
        raise ValueError("explicit deal identities missing; --allow-legacy permits only metadata-based legacy pairing")
    context = result.get("evaluation_context")
    if context is not None:
        if not isinstance(context, dict) or context.get("schema") != CONTEXT_SCHEMA:
            raise ValueError("invalid frozen evaluation context")
        for key in ("inputs_sha256", "candidate_inputs_sha256", "inventory_sha256"):
            fingerprint = context.get(key)
            if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
                raise ValueError(f"invalid frozen-input fingerprint: {key}")
        if type(context.get("workers")) is not int or context["workers"] < 1:
            raise ValueError("invalid worker count")
        if context.get("design") != "4_rotations_2_teams" or context.get("chunksize") != 8:
            raise ValueError("unknown duplicate evaluation design")
        if context.get("controller_state") != "persistent_per_worker":
            raise ValueError("unknown controller-state design")
    elif not allow_legacy:
        raise ValueError("frozen-input context missing; use queue outputs or explicitly --allow-legacy")
    if "seconds" in result and _number(result["seconds"], "elapsed seconds") < 0:
        raise ValueError("elapsed seconds must be nonnegative")
    return result


def compare(candidate: dict, reference: dict, *, allow_legacy: bool = False) -> dict:
    """Pair the exact same complete sample set; never truncate or intersect silently."""
    for result in (candidate, reference):
        validate_result(result, allow_legacy=allow_legacy)
    for key in META:
        if candidate[key] != reference[key]:
            raise ValueError(f"incompatible {key}: {candidate[key]!r} versus {reference[key]!r}")
    if candidate["base_deals"] != reference["base_deals"]:
        raise ValueError("unequal sample counts; prefix truncation is not permitted")
    contexts = [r.get("evaluation_context") for r in (candidate, reference)]
    if all(c is not None for c in contexts) and any(contexts[0][key] != contexts[1][key] for key in SHARED_CONTEXT):
        raise ValueError("frozen inputs or execution design differ")
    records = [r.get("deal_records") for r in (candidate, reference)]
    warnings = []
    if all(rows is not None for rows in records):
        a, b = ({row["deal_id"]: row for row in rows} for rows in records)
        if a.keys() != b.keys():
            raise ValueError("different deal sets; intersection pairing is not permitted")
        deltas = []
        for identity, row in a.items():
            if row["index"] != b[identity]["index"] or row["score"] != b[identity]["score"]:
                raise ValueError("inconsistent deal identity metadata")
            deltas.append(row["value"] - b[identity]["value"])
        level = "deal_ids_and_frozen_inputs" if all(contexts) else "deal_ids_without_frozen_inputs"
    else:
        # Explicit request only: old evaluator guarantees range(n) order, but
        # its output cannot independently attest which cards were actually used.
        a = ([row["value"] for row in sorted(rows, key=lambda r: r["index"])] if rows is not None else r["values"]
             for r, rows in zip((candidate, reference), records))
        left, right = a
        deltas = [x - y for x, y in zip(left, right)]
        level = "legacy_metadata_only"
        warnings.append("Deal identity inferred from seed and index; actual dealt cards are not attested.")
    if not all(contexts):
        warnings.append("Source/model/native/equity identity is not verified for both results.")
    n, mean = len(deltas), statistics.fmean(deltas)
    se = statistics.stdev(deltas) / math.sqrt(n)
    return {"schema": "tuppi.paired_comparison.v1", "candidate": candidate["candidate"],
            "reference": reference["candidate"], **{key: candidate[key] for key in META},
            "base_deals": n, "validation_level": level, "warnings": warnings,
            "equity_delta": mean, "ci95": [mean - 1.96 * se, mean + 1.96 * se],
            "standard_error": se, "positive_delta_deals": sum(v > 0 for v in deltas),
            "zero_delta_deals": sum(v == 0 for v in deltas), "paired_deltas": deltas,
            "candidate_seconds": candidate.get("seconds"), "reference_seconds": reference.get("seconds"),
            "candidate_context": contexts[0], "reference_context": contexts[1],
            "qualification": "Candidate minus reference against the same opponent. Normal-approximation interval over base deals; persistent controllers can introduce dependence. No correction for tuning or multiple comparisons."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate", type=Path)
    p.add_argument("reference", type=Path)
    p.add_argument("--allow-legacy", action="store_true", help="explicitly accept unverified legacy identities/provenance")
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    try:
        report = compare(read_json(a.candidate), read_json(a.reference), allow_legacy=a.allow_legacy)
        if a.out:
            write_json(a.out, report, replace=False)
    except (ValueError, KeyError, TypeError, OSError) as e:
        p.error(str(e))
    print(canonical(report).decode())


if __name__ == "__main__":
    main()
