"""Outcome metrics and diagnostic strata separated from paired inference."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from .config import EvaluationConfiguration
from .records import DuplicateBlockRecord, ExecutionStatus, GameRecord
from .statistics import paired_statistical_summary


SUMMARY_SCHEMA_VERSION = "tuppi.eval.summary.v1"
SMALL_STRATUM_WARNING_THRESHOLD = 10


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = probability * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _external_engine_team(record: GameRecord, external: str) -> int:
    return 0 if record.seat_external_teams[0] == external else 1


def _score_state(record: GameRecord) -> str:
    if record.starting_score == (0, 0):
        return "0-0"
    up_engine = 0 if record.starting_score[0] > 0 else 1
    external = record.seat_external_teams[up_engine]
    return f"{external}_up"


def _team_a_score_status(record: GameRecord) -> str:
    if record.starting_score == (0, 0):
        return "0-0"
    up_engine = 0 if record.starting_score[0] > 0 else 1
    return "up" if record.seat_external_teams[up_engine] == "A" else "down"


def _rami_outcome(record: GameRecord) -> str:
    if record.contract != "RAMI":
        return "not_rami"
    return (
        "successful_rami"
        if record.declaring_external_team == record.winner_external_team
        else "stolen_rami"
    )


def _strata(records: tuple[GameRecord, ...]) -> dict[str, object]:
    dimensions: dict[str, dict[str, list[GameRecord]]] = {
        name: defaultdict(list)
        for name in (
            "agent_partnership_assignment",
            "contract",
            "contract_x_score_state",
            "dealer_seat",
            "deal_point_magnitude",
            "declarer_seat",
            "declaring_team",
            "first_leader",
            "forehand_seat",
            "rami_outcome",
            "starting_score",
            "score_state",
            "team_a_up_down_status",
            "transformation",
        )
    }
    for record in records:
        assignment = "A_even" if record.seat_external_teams[0] == "A" else "A_odd"
        keys = {
            "agent_partnership_assignment": assignment,
            "contract": record.contract or "none",
            "contract_x_score_state": (
                f"{record.contract or 'none'}:{_team_a_score_status(record)}"
            ),
            "dealer_seat": str(record.dealer),
            "deal_point_magnitude": str(record.deal_points),
            "declarer_seat": "none" if record.declarer is None else str(record.declarer),
            "declaring_team": record.declaring_external_team or "none",
            "first_leader": (
                "none" if record.first_leader is None else str(record.first_leader)
            ),
            "forehand_seat": str(record.forehand),
            "rami_outcome": _rami_outcome(record),
            "starting_score": f"{record.starting_score[0]}-{record.starting_score[1]}",
            "score_state": _score_state(record),
            "team_a_up_down_status": _team_a_score_status(record),
            "transformation": record.transformation_id,
        }
        for dimension, key in keys.items():
            dimensions[dimension][key].append(record)
    result: dict[str, object] = {}
    for dimension, groups in dimensions.items():
        result[dimension] = {
            key: {
                "independent_base_deals": len(
                    {record.base_deal_id for record in group}
                ),
                "mean_signed_game_utility": fmean(
                    record.signed_utility for record in group  # type: ignore[arg-type]
                ),
                "n_transformed_games": len(group),
                "team_a_game_win_rate": sum(
                    record.winner_external_team == "A" for record in group
                )
                / len(group),
                "warning": (
                    "small diagnostic stratum; descriptive, not causal"
                    if len({record.base_deal_id for record in group})
                    < SMALL_STRATUM_WARNING_THRESHOLD
                    else None
                ),
            }
            for key, group in sorted(groups.items())
        }
    return result


def build_evaluation_summary(
    records: tuple[GameRecord, ...],
    blocks: tuple[DuplicateBlockRecord, ...],
    config: EvaluationConfiguration,
) -> dict[str, object]:
    successful = tuple(
        record
        for record in records
        if record.execution_status is ExecutionStatus.SUCCESS
    )
    failures = len(records) - len(successful)
    durations = [record.duration_seconds for record in records]
    action_durations = [
        duration
        for record in records
        for duration in record.action_durations_seconds
    ]
    a_wins = sum(record.winner_external_team == "A" for record in successful)
    b_wins = sum(record.winner_external_team == "B" for record in successful)
    rami = tuple(record for record in successful if record.contract == "RAMI")
    nolo = tuple(record for record in successful if record.contract == "NOLO")
    successful_rami = sum(
        record.declaring_external_team == record.winner_external_team
        for record in rami
    )
    stolen_rami = len(rami) - successful_rami
    points_a = [
        record.deal_points
        for record in successful
        if record.winner_external_team == "A" and record.deal_points is not None
    ]
    points_b = [
        record.deal_points
        for record in successful
        if record.winner_external_team == "B" and record.deal_points is not None
    ]
    a_tricks: list[int] = []
    b_tricks: list[int] = []
    for record in successful:
        if record.team_tricks is None:
            continue
        a_engine = _external_engine_team(record, "A")
        b_engine = 1 - a_engine
        a_tricks.append(record.team_tricks[a_engine])
        b_tricks.append(record.team_tricks[b_engine])
    statistical = paired_statistical_summary(
        blocks,
        confidence_level=config.confidence_level,
        analysis_seed=config.seed_hierarchy.analysis_seed,
        bootstrap_replicates=config.bootstrap_replicates,
        permutation_replicates=config.permutation_replicates,
    )
    return {
        "contract_metrics": {
            "nolo_count": len(nolo),
            "nolo_rate": len(nolo) / len(successful) if successful else None,
            "rami_count": len(rami),
            "rami_declaration_rate": (
                len(rami) / len(successful) if successful else None
            ),
            "stolen_rami_count": stolen_rami,
            "stolen_rami_rate_given_rami": (
                stolen_rami / len(rami) if rami else None
            ),
            "successful_rami_count": successful_rami,
            "successful_rami_rate_given_rami": (
                successful_rami / len(rami) if rami else None
            ),
        },
        "evaluation_id": config.evaluation_id,
        "evaluation_mode": config.evaluation_mode.value,
        "execution_metrics": {
            "decision_failure_rate": failures / len(records) if records else None,
            "failed_games": failures,
            "mean_action_seconds": fmean(action_durations) if action_durations else None,
            "mean_game_seconds": fmean(durations) if durations else None,
            "p50_action_seconds": _percentile(action_durations, 0.50),
            "p50_game_seconds": _percentile(durations, 0.50),
            "p95_action_seconds": _percentile(action_durations, 0.95),
            "p95_game_seconds": _percentile(durations, 0.95),
            "successful_games": len(successful),
        },
        "outcome_metrics": {
            "match_win_rate_team_a": (
                sum(record.match_winner_external_team == "A" for record in successful)
                / len(successful)
                if successful and config.evaluation_mode.value == "match"
                else None
            ),
            "mean_deal_points_conditional_team_a_win": (
                fmean(points_a) if points_a else None
            ),
            "mean_deal_points_conditional_team_b_win": (
                fmean(points_b) if points_b else None
            ),
            "mean_tricks_team_a": fmean(a_tricks) if a_tricks else None,
            "mean_tricks_team_b": fmean(b_tricks) if b_tricks else None,
            "reset_rate": (
                sum(record.reset is True for record in successful) / len(successful)
                if successful
                else None
            ),
            "team_a_deal_win_rate": a_wins / len(successful) if successful else None,
            "team_b_deal_win_rate": b_wins / len(successful) if successful else None,
        },
        "primary_inference": statistical,
        "primary_metric_definition": (
            "For each complete eight-game duplicate block, assign +deal_points "
            "when Team A wins and -deal_points when Team B wins, then average "
            "the eight signed values. Inference treats those base-deal averages, "
            "not transformed games, as independent observations."
        ),
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "strata": _strata(successful),
    }
