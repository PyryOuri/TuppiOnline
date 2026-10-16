"""Strict parent-paired summaries and identification bounds for censored matches."""
from __future__ import annotations
import math
import statistics


def interval(values):
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError("A complete finite sample is required")
    mean = statistics.fmean(values)
    if len(values) < 2:
        return {"mean": mean, "ci95": None, "standard_error": None}
    se = statistics.stdev(values) / math.sqrt(len(values))
    return {"mean": mean, "ci95": [mean - 1.96 * se, mean + 1.96 * se], "standard_error": se}


def paired(candidate, reference):
    for key in ("schema", "seed", "ruleset", "scores", "opponent", "context", "base_deals", "dependency_versions"):
        if candidate.get(key) != reference.get(key):
            raise ValueError(f"Incompatible {key}")
    if candidate.get("schema") != "tuppi.cheap_wins.duplicate.v1":
        raise ValueError("Not a complete duplicate-deal result")
    if not isinstance(candidate.get("dependency_versions"), dict):
        raise ValueError("Runtime dependency identities missing")
    n = candidate["base_deals"]
    if type(n) is not int or n < 2:
        raise ValueError("At least two complete parent deals required")
    context = candidate.get("context")
    if not isinstance(context, dict) or context.get("controller_lifecycle") != "fresh_indexed_game" or context.get("design") != "4_rotations_2_teams":
        raise ValueError("Unknown/missing frozen lifecycle context")
    identity = context.get("package_sha256", "")
    if len(identity) != 64 or any(x not in "0123456789abcdef" for x in identity):
        raise ValueError("Missing sealed package identity")
    def records(result):
        rows = result["deal_records"]
        if len(rows) != n or len(result["values"]) != n:
            raise ValueError("Incomplete parent set")
        out = {}
        for i, row in enumerate(rows):
            identity, index, value = row["deal_id"], row["index"], row["value"]
            if len(identity) != 64 or any(x not in "0123456789abcdef" for x in identity) or identity in out:
                raise ValueError("Invalid/duplicate parent identity")
            if type(index) is not int or not 0 <= index < n or not math.isfinite(value) or abs(value) > 1:
                raise ValueError("Invalid parent record")
            if value != result["values"][i] or len(row["games"]) != 8:
                raise ValueError("Parent values/games disagree")
            game_ids = [(g["rotation"], g["team"]) for g in row["games"]]
            if set(game_ids) != {(rotation, team) for rotation in range(4) for team in (0, 1)}:
                raise ValueError("Duplicate/missing indexed game")
            if any(len(g["fingerprint"]) != 64 or any(x not in "0123456789abcdef" for x in g["fingerprint"]) for g in row["games"]):
                raise ValueError("Invalid completed-game fingerprint")
            if not all(math.isfinite(g["value"]) and abs(g["value"]) <= 1 for g in row["games"]) or value != statistics.fmean(g["value"] for g in row["games"]):
                raise ValueError("Parent mean disagrees with completed games")
            out[identity] = row
        if {r["index"] for r in rows} != set(range(n)):
            raise ValueError("Duplicate/missing parent index")
        return out
    left, right = records(candidate), records(reference)
    if left.keys() != right.keys():
        raise ValueError("Different parent sets; no intersection pairing")
    deltas = []
    for identity, row in left.items():
        other = right[identity]
        if row["index"] != other["index"] or row["score"] != other["score"]:
            raise ValueError("Different parent metadata")
        deltas.append(row["value"] - other["value"])
    return {"schema": "tuppi.cheap_wins.paired.v1", "candidate": candidate["candidate"],
            "reference": reference["candidate"], "base_deals": n, "paired_deltas": deltas,
            **interval(deltas), "context": candidate["context"],
            "qualification": "Candidate minus reference against the same opponent; normal interval across independent parent bundles. No multiple-comparison or tuning adjustment."}


def match_pair(a, b):
    for leg in (a, b):
        if leg["censored"] and leg["result"] is not None:
            raise ValueError("Censored outcome must be unknown")
        if not leg["censored"] and leg["result"] not in (0.0, 1.0):
            raise ValueError("Completed match must have a winner")
    low = sum(0.0 if leg["censored"] else leg["result"] for leg in (a, b)) / 2
    high = sum(1.0 if leg["censored"] else leg["result"] for leg in (a, b)) / 2
    censored = sum(leg["censored"] for leg in (a, b))
    return {"score": low if not censored else None, "lower": low, "upper": high,
            "censored_legs": censored, "deals": a["deals"] + b["deals"], "legs": [a, b]}


def matches(rows):
    if not rows:
        raise ValueError("No match pairs")
    censored = sum(r["censored_legs"] for r in rows)
    complete = interval([r["score"] for r in rows]) if not censored else None
    return {"p_win": complete["mean"] if complete else None, "ci95": complete["ci95"] if complete else None,
            "p_win_bounds": [statistics.fmean(r["lower"] for r in rows), statistics.fmean(r["upper"] for r in rows)],
            "bounds_are": "Identification bounds for unresolved outcomes, not confidence intervals",
            "censored_legs": censored, "complete_pairs": sum(r["score"] is not None for r in rows)}


def compare_traces(candidate, reference):
    if candidate.get("schema") != "tuppi.cheap_wins.full_deals.v1" or reference.get("schema") != candidate["schema"]:
        raise ValueError("Not full-deal trace results")
    for key in ("context", "dependency_versions"):
        if not isinstance(candidate.get(key), dict) or candidate.get(key) != reference.get(key):
            raise ValueError(f"Different {key}")
    for key in ("samples", "worlds", "seed", "scores", "serial"):
        if candidate["job"][key] != reference["job"][key]:
            raise ValueError(f"Different trace design: {key}")
    n = candidate["job"]["samples"]
    if type(n) is not int or n < 1 or len(candidate["rows"]) != n or len(reference["rows"]) != n:
        raise ValueError("Incomplete trace set")
    if [r["index"] for r in candidate["rows"]] != list(range(n)) or [r["index"] for r in reference["rows"]] != list(range(n)):
        raise ValueError("Different/duplicate trace indices")
    for result in (candidate, reference):
        for row in result["rows"]:
            identity = row["fingerprint"]
            if len(identity) != 64 or any(x not in "0123456789abcdef" for x in identity):
                raise ValueError("Invalid trace fingerprint")
    mismatches = [a["index"] for a, b in zip(candidate["rows"], reference["rows"]) if a["fingerprint"] != b["fingerprint"]]
    times = [candidate["cpu_seconds"], reference["cpu_seconds"]]
    if not all(math.isfinite(t) and t > 0 for t in times + [candidate["seconds"], reference["seconds"]]):
        raise ValueError("Invalid cost measures")
    return {"schema": "tuppi.cheap_wins.trace_comparison.v1", "candidate": candidate["candidate"], "reference": reference["candidate"],
            "fingerprints_identical": not mismatches, "mismatched_deals": mismatches, "deals": n,
            "classification": "exact_on_checked_traces" if not mismatches else "numerical_or_policy_variant",
            "cpu_reference_over_candidate": times[1] / times[0],
            "wall_reference_over_candidate": reference["seconds"] / candidate["seconds"],
            "qualification": "Fixed-input cost observation. Whole-deal equality is required for an exact speed claim; repeat alternating runs before estimating general speed."}
