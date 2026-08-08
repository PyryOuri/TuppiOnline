"""Assemble the committed Phase 5D-A report from the run artifacts."""
from __future__ import annotations
import os
import pathlib, sys
from tuppi_engine import atomic_write_canonical_json, strict_json_load_file
from tuppi_search.registry import (
    negative_baseline_designation, phase5d_a_registry_snapshot, registry_snapshot,
)
from tuppi_search.validation import boundary_report

RUNS = pathlib.Path(
    os.environ.get(
        "TUPPI_RUNS_DIR",
        str(pathlib.Path.home() / "TuppiRuns" / "phase5d-a"),
    )
)
REPORTS = pathlib.Path("reports/phase5d_a")
REPORTS.mkdir(parents=True, exist_ok=True)


def optional(*names: str):
    for name in names:
        path = RUNS / name
        if path.exists():
            return strict_json_load_file(str(path)), name
    return None, None


registry = phase5d_a_registry_snapshot()
registry["boundary_report"] = boundary_report()
atomic_write_canonical_json(str(REPORTS / "phase5d_a_registry.json"), registry)

phase5c = strict_json_load_file("reports/phase5c/phase5c_evaluation.json")
findings = {
    "schema_version": "tuppi.search.phase5d_a_report.v1",
    "purpose": (
        "Decompose the Phase 5C PIMC failure before choosing a next search family. "
        "Every experiment uses a fresh unsealed development bank."
    ),
    "phase5c_negative_baseline": negative_baseline_designation(),
    "phase5c_quoted_result": {
        "note": (
            "Quoted from the committed Phase 5C artifact, not recomputed. Phase 5D-A "
            "does not revisit or adjust it."
        ),
        "primary_match_inference": phase5c["primary_complete_match_comparison"][
            "primary_match_inference"
        ],
    },
    "phase5c_registry_digest_unchanged": registry_snapshot()["registry_digest"],
    "promotion_status": (
        "No Phase 5D-A result is promotion evidence. Every bank used is a development "
        "bank and the promotion-sealed bank was never opened."
    ),
}
findings["safety_cap_deviation"] = {
    "phase5c_safety_cap": 704,
    "phase5d_a_safety_cap": 96,
    "censoring_observed": (
        "Zero pairs censored in both homogeneous comparisons; the longest single leg "
        "ran 71 deals, so the reduced cap never bound."
    ),
    "rationale": (
        "Phase 5D-A candidates are stronger than Phase 5C's, and project_target_v1 "
        "resets the score to 0-0 whenever the down team wins a deal, so near-parity "
        "legs run long. A first attempt at the play-only comparison under the Phase 5C "
        "cap of 704 ran ten hours across six workers without completing one pair. "
        "Censoring is not missing-at-random - it removes the closest legs - so the cap "
        "and the observed censoring are both recorded rather than assumed harmless."
    ),
}
findings["selected_path"] = {
    "path": "unresolved",
    "eliminated": ["A"],
    "open": ["B", "D"],
    "justification": (
        "Path A is eliminated as the primary cause: handing showing back to the frozen "
        "reference leaves uniform_feasible_pimc_play_only_v1 at p_win 0.250 with a 95% "
        "interval of [0.059, 0.441] that excludes parity, and show-only is separately "
        "negative at 0.333, so neither phase is the single cause. Path C is not "
        "supported and, per the pre-registered rule, would not be selected merely "
        "because four worlds is unconverged. Path B has strong mechanistic support - "
        "the rollout-mismatch control matches perfectly in 20 of 20 positions with a "
        "reference partner and diverges in 19 of 20 with a PIMC partner, inside the "
        "root team in 35 of 38 cases - but divergence is not causation, and the "
        "seat-balanced heterogeneous comparison that would convert it into a strength "
        "claim did not run. Path D remains open on the same missing evidence."
    ),
    "licenses_next": (
        "Not ISMCTS yet. Run the seat-balanced heterogeneous comparison first: it "
        "separates the two live hypotheses and costs far less than a new search "
        "family. See docs/search/phase5d_a_handoff.md."
    ),
}
findings["corpus_defect_retracted"] = {
    "what": (
        "The first decision corpus filled its trick-play target in encounter order, so "
        "all 96 trick-play positions came from one set of hands and its 48 showing "
        "positions from three."
    ),
    "how_found": (
        "The corpus put the reference RAMI declaration rate at 0.083 while a direct "
        "measurement of the same policy on the same bank gave 0.250."
    ),
    "retracted_claim": (
        "That the PIMC RAMI bias was perfectly one-directional (21 flips to 0). On the "
        "corrected 32-hand corpus it is 33 to 9, a ratio of 3.7 to 1."
    ),
    "fix": (
        "build_corpus caps the positions one hand may contribute, spaces kept card "
        "decisions across tricks, and plays each hand at one rotated score state; "
        "tests/search/test_phase5d_diagnostics.py asserts the deal-spread property."
    ),
}
artifact_sources = {}
for key, names in (
    ("play_only_complete_match", ("match_play_only_12.json",)),
    ("show_only_complete_match", ("match_show_only_12.json",)),
    ("heterogeneous_full_pimc", ("hetero_full_pimc_12.json",)),
    ("heterogeneous_play_only", ("hetero_play_only_12.json",)),
    ("full_pimc_same_bank", ("match_full_pimc_12.json",)),
    ("deal_screen", ("screen_play_only.json",)),
    ("decomposition", ("decomposition_v2.json", "decomposition_full.json")),
    ("convergence", ("convergence.json", "convergence_v2.json")),
):
    value, source = optional(*names)
    if value is not None:
        findings[key] = value
        artifact_sources[key] = source
    else:
        findings.setdefault("not_run", []).append(names[0])

if artifact_sources.get("convergence") == "convergence.json":
    findings["convergence"]["provisional"] = (
        "Measured on the defective corpus described in corpus_defect_retracted: 24 of "
        "its trick-play positions came from a single set of hands. Re-run on the "
        "corrected corpus before relying on the selection-gap series."
    )

heterogeneous = findings.get("heterogeneous_full_pimc")
if heterogeneous is not None:
    arrangements = heterogeneous.get("arrangements", [])
    inferences = [item["primary_match_inference"] for item in arrangements]
    if inferences and all(
        item["candidate_match_win_probability"] < 0.5 for item in inferences
    ):
        findings["selected_path"] = {
            "path": "D",
            "eliminated": ["A", "B", "C"],
            "open": [],
            "justification": (
                "Path A is eliminated as the primary cause: handing showing back to the "
                "frozen reference leaves play-only at p_win 0.250 and show-only at "
                "0.333, so neither phase is the single cause. Path B is not supported "
                "by the seat-balanced heterogeneous comparison: the two PIMC-seat "
                "arrangements reached p_win 0.333 and 0.375, both below parity, with "
                "one arrangement having 3 censored pairs and the other none. Path C is "
                "not supported by the corrected convergence run: adjacent agreement "
                "was 0.839, 0.830, 0.839, and 0.875 from 2 to 32 worlds, with 16 to "
                "32 worlds agreeing on 98 of 112 positions. Path D is therefore the "
                "selected development path, subject to the recorded small-sample and "
                "censoring limits."
            ),
            "licenses_next": (
                "Freeze uniform_feasible_pimc_small_v1 as a negative baseline and begin "
                "an observation-safe information-set search phase. The promotion-sealed "
                "bank remains closed."
            ),
        }

atomic_write_canonical_json(str(REPORTS / "phase5d_a_findings.json"), findings)
for path in sorted(REPORTS.iterdir()):
    print(f"  {path}  {path.stat().st_size} bytes")
print("sections:", sorted(k for k in findings if k not in ("schema_version",)))
