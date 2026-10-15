"""Match-equity diagnostics from explicit nonterminal score states.

The primary endpoint is measured from 0-0 and nothing else. These diagnostics
answer a different, secondary question: *given that the match has reached this
score, how often does each partnership go on to win it?*

Each diagnostic still runs a complete match to natural termination on the same
extensible deterministic stream, so the answer is a match-win probability and
not a next-deal score. Complementary team assignments mean every evaluated team
appears once as the up team and once as the down team at each asymmetric score.

These results are secondary. They must be reported separately from the official
0-0 distribution and can never override it.
"""

from __future__ import annotations

from tuppi_rules import MATCH_TARGET

from .errors import MatchValidationError
from .manifest import MatchComparison


DIAGNOSTIC_SCHEMA_VERSION = "tuppi.match.score_state_diagnostics.v1"

#: The required diagnostic score states. Each asymmetric score appears in both
#: orientations so that a candidate is evaluated as the up team and the down
#: team, and 0-0 is included as the anchor that ties the diagnostics to the
#: primary distribution.
DIAGNOSTIC_SCORES: tuple[tuple[int, int], ...] = (
    (0, 0),
    (16, 0),
    (0, 16),
    (32, 0),
    (0, 32),
    (44, 0),
    (0, 44),
    (48, 0),
    (0, 48),
)


def validate_diagnostic_scores() -> tuple[tuple[int, int], ...]:
    for score in DIAGNOSTIC_SCORES:
        if len(score) != 2 or any(value < 0 for value in score):
            raise MatchValidationError("a diagnostic score must be a nonnegative pair")
        if max(score) >= MATCH_TARGET:
            raise MatchValidationError("a diagnostic score must be nonterminal")
        if score[0] > 0 and score[1] > 0:
            raise MatchValidationError(
                "project_target_v1 allows only one partnership to hold points"
            )
    return DIAGNOSTIC_SCORES


def score_state_comparisons(
    *,
    candidate_profile_key: str,
    opponent_profile_key: str,
    candidate_agent_id: str,
    opponent_agent_id: str,
    result_class: str = "ablation",
    scores: tuple[tuple[int, int], ...] = DIAGNOSTIC_SCORES,
) -> tuple[MatchComparison, ...]:
    """Build one comparison per diagnostic score state.

    The duplicate design already gives each partnership both seat orientations
    inside a pair. Running both ``(n, 0)`` and ``(0, n)`` additionally gives the
    candidate both *score* roles: engine team 0 holds the points in the first
    and team 1 holds them in the second, and the candidate occupies each engine
    team once per pair.
    """

    validate_diagnostic_scores()
    built = []
    for score in scores:
        label = "table" if score == (0, 0) else f"{score[0]}-{score[1]}"
        built.append(
            MatchComparison.build(
                name=(
                    f"diag_{candidate_profile_key}_vs_{opponent_profile_key}_{label}"
                ),
                candidate_profile_key=candidate_profile_key,
                opponent_profile_key=opponent_profile_key,
                candidate_agent_id=candidate_agent_id,
                opponent_agent_id=opponent_agent_id,
                result_class=result_class,
                hypothesis=(
                    "Secondary score-state diagnostic: match-win probability "
                    f"from an explicit {label} start, played to natural "
                    "termination on the same deterministic stream."
                ),
                starting_score=score,
            )
        )
    return tuple(built)


def summarize_score_states(report: dict[str, object]) -> dict[str, object]:
    """Group a report's diagnostic comparisons by their starting score."""

    rows = []
    for comparison in report.get("comparisons", []):
        score = tuple(comparison["starting_score"])
        if score == (0, 0) and not comparison["name"].startswith("diag_"):
            continue
        inference = comparison["primary_match_inference"]
        secondary = comparison["secondary_metrics"]
        rows.append(
            {
                "candidate_match_win_probability": inference[
                    "candidate_match_win_probability"
                ],
                "candidate_profile_key": comparison["candidate_profile_key"],
                "censored_pair_count": inference["censored_pair_count"],
                "complete_pair_count": inference["complete_pair_count"],
                "confidence_interval": inference["win_probability_confidence_interval"],
                "immediate_completion_rate": secondary.get(
                    "immediate_completion_rate"
                ),
                "mean_deals_per_match": (
                    secondary.get("deals_per_match", {}).get("mean")
                ),
                "name": comparison["name"],
                "opponent_profile_key": comparison["opponent_profile_key"],
                "resets_per_match_mean": (
                    secondary.get("resets_per_match", {}).get("mean")
                ),
                "starting_score": list(score),
            }
        )
    return {
        "note": (
            "Secondary diagnostics. They describe conditional match equity from "
            "explicit score states and never replace the 0-0 primary endpoint."
        ),
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "score_states": sorted(rows, key=lambda item: (item["starting_score"], item["name"])),
    }
