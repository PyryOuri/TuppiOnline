"""The committed Phase 5A calibration design and its safety-cap calibration.

Two things live here: the named banks and comparisons that the calibration run
uses, and the procedure that turns an observed match-length distribution into a
defensible safety cap.

The cap is an *infrastructure* safeguard. Phase 4 used 40, which turned out to
sit near the median observed match length, so a third of all pairs were
censored and the surviving pairs were biased toward the streams where the two
policies happened to agree. The replacement is chosen from data: take the
maximum observed length, multiply by a headroom factor, and round up. It is
recorded in the manifest together with the reason.
"""

from __future__ import annotations

import math

from .banks import BankRole, StreamBank
from .errors import MatchValidationError
from .manifest import MatchComparison
from .statistics import length_distribution


CALIBRATION_ROOT_SEED = "tuppi-phase5a-calibration-v1"
DEVELOPMENT_ROOT_SEED = "tuppi-phase5a-development-v1"
DIAGNOSTIC_ROOT_SEED = "tuppi-phase5a-diagnostics-v1"

CALIBRATION_STREAM_COUNT = 512
DEVELOPMENT_STREAM_COUNT = 64
DIAGNOSTIC_STREAM_COUNT = 128

#: Multiplied by the longest observed match to leave headroom for the tail that
#: a finite sample has not shown yet.
SAFETY_CAP_HEADROOM = 3.0
SAFETY_CAP_FLOOR = 256

#: The ladder steps the calibration must answer, plus the ablation that Phase 4
#: could not measure.
LADDER_STEPS: tuple[tuple[str, str, str], ...] = (
    (
        "reactive_contract_v1",
        "legacy_heuristic_port_v1",
        "Does the transparent reactive baseline beat the ported legacy heuristic "
        "over complete matches?",
    ),
    (
        "public_counting_v1",
        "reactive_contract_v1",
        "Does hard public inference beat the reactive baseline over complete "
        "matches?",
    ),
    (
        "partner_aware_v1",
        "public_counting_v1",
        "Do explicit partnership rules beat public counting over complete "
        "matches?",
    ),
    (
        "match_aware_v1",
        "partner_aware_v1",
        "Do the deterministic rising-score rules beat partner awareness when the "
        "endpoint is the match rather than the deal margin?",
    ),
)

ABLATION_STEP: tuple[str, str, str] = (
    "match_aware_v1",
    "match_aware_no_match_features_v1",
    "The first valid measurement of the match-aware features: identical policy "
    "with every rising-score rule switched off, scored on match wins.",
)


def calibration_bank(*, stream_count: int = CALIBRATION_STREAM_COUNT) -> StreamBank:
    return StreamBank.build(
        name="phase5a_calibration_v1",
        role=BankRole.CALIBRATION,
        root_seed=CALIBRATION_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Estimate match length, paired variance, leg correlation, censoring "
            "probability, contract frequencies, and execution cost. Inspected "
            "after execution; never a tuning loop and never promotion evidence."
        ),
    )


def development_bank(*, stream_count: int = DEVELOPMENT_STREAM_COUNT) -> StreamBank:
    return StreamBank.build(
        name="phase5a_development_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=DEVELOPMENT_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Visible, debuggable, reusable. Supports no promotion claim of any "
            "kind."
        ),
    )


def diagnostic_bank(*, stream_count: int = DIAGNOSTIC_STREAM_COUNT) -> StreamBank:
    return StreamBank.build(
        name="phase5a_score_state_diagnostics_v1",
        role=BankRole.DEVELOPMENT,
        root_seed=DIAGNOSTIC_ROOT_SEED,
        initial_dealer=0,
        stream_count=stream_count,
        purpose=(
            "Secondary conditional match-equity diagnostics from explicit score "
            "states. Never part of the 0-0 primary distribution."
        ),
    )


def ladder_comparisons(*, result_class: str = "calibration") -> tuple[MatchComparison, ...]:
    from tuppi_agents import phase4_specifications_by_profile_key

    specifications = phase4_specifications_by_profile_key()
    built = []
    for candidate, opponent, hypothesis in LADDER_STEPS + (ABLATION_STEP,):
        built.append(
            MatchComparison.build(
                name=f"match_{candidate}_vs_{opponent}",
                candidate_profile_key=candidate,
                opponent_profile_key=opponent,
                candidate_agent_id=specifications[candidate].agent_id,
                opponent_agent_id=specifications[opponent].agent_id,
                result_class=(
                    "ablation"
                    if (candidate, opponent) == ABLATION_STEP[:2]
                    else result_class
                ),
                hypothesis=hypothesis,
            )
        )
    return tuple(built)


def calibrate_safety_cap(
    observed_lengths: list[int],
    *,
    headroom: float = SAFETY_CAP_HEADROOM,
    floor: int = SAFETY_CAP_FLOOR,
) -> dict[str, object]:
    """Turn an observed match-length sample into a defensible safety cap.

    The cap is deliberately not a quantile of the sample. A quantile would
    censor by design at exactly the rate it names; the point of the cap is that
    censoring should be *exceptional*, so it is placed well beyond the longest
    match anyone has actually seen.
    """

    if not observed_lengths:
        raise MatchValidationError("safety-cap calibration needs observed lengths")
    if headroom < 1.0:
        raise MatchValidationError("headroom must be at least 1.0")
    distribution = length_distribution(observed_lengths)
    longest = int(distribution["maximum"])
    proposed = max(floor, int(math.ceil(longest * headroom / 64.0)) * 64)
    return {
        "distribution": distribution,
        "headroom_factor": headroom,
        "longest_observed": longest,
        "method": (
            "ceil(longest_observed * headroom) rounded up to a multiple of 64, "
            f"floored at {floor}"
        ),
        "observed_over_proposed_cap": sum(
            1 for value in observed_lengths if value >= proposed
        ),
        "proposed_safety_cap": proposed,
        "rationale": (
            "An infrastructure safeguard, not a modelling choice. Placed beyond "
            "the longest observed match so that censoring is exceptional rather "
            "than routine, unlike the Phase 4 cap of 40 which sat near the "
            "median."
        ),
        "sample_size": len(observed_lengths),
    }
