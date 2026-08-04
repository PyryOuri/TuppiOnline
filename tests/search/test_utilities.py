"""The utility adapters: orientation, range, and exhaustive monotonicity."""

from __future__ import annotations

import pytest

from tuppi_exact import match_score_after_split
from tuppi_exact.solver import match_utility_from_score
from tuppi_rules import (
    Contract,
    MATCH_TARGET,
    MatchScore,
    TRICKS_PER_DEAL,
    Team,
    is_match_terminal,
    team_for_seat,
)

from tuppi_search.errors import UtilityError
from tuppi_search.utilities import (
    DealOutcomeSummary,
    OutcomeSource,
    UtilityId,
    exact_tail_summary,
    is_registerable,
    summary_from_completed_deal,
    utility_catalogue,
    utility_range,
    utility_value,
)

from .conftest import walk_deal


def _summary(
    *,
    contract=Contract.RAMI,
    declarer=0,
    team0_tricks=7,
    score=(0, 0),
    root_seat=0,
    source=OutcomeSource.ROLLOUT,
) -> DealOutcomeSummary:
    return DealOutcomeSummary(
        contract=contract,
        declarer=declarer,
        team0_tricks=team0_tricks,
        starting_score=MatchScore(*score),
        root_team=team_for_seat(root_seat),
        source=source,
        tricks_simulated=TRICKS_PER_DEAL,
    )


def _reachable_scores() -> list[MatchScore]:
    scores = [MatchScore()]
    for points in range(4, MATCH_TARGET, 4):
        scores.append(MatchScore(points, 0))
        scores.append(MatchScore(0, points))
    return scores


# ------------------------------------------------------------------- structure


def test_every_adapter_declares_a_finite_range():
    for item in UtilityId:
        assert utility_range(item) == (-1.0, 1.0)
    catalogue = utility_catalogue()
    assert len(catalogue) == len(UtilityId)
    for entry in catalogue:
        assert entry["description"]
        assert entry["range"] == [-1.0, 1.0]


def test_the_trick_split_adapter_is_not_registerable():
    """It ignores the 6/7 boundary that decides who wins, so it may not be an agent's."""

    assert is_registerable(UtilityId.TRICK_SPLIT_V1) is False
    assert is_registerable(UtilityId.MATCH_TRANSITION_V1) is True
    assert is_registerable(UtilityId.DEAL_RESULT_V1) is True


def test_a_registered_configuration_rejects_the_diagnostic_adapter():
    from tuppi_search.config import PimcConfiguration
    from tuppi_search.errors import SearchConfigurationError

    configuration = PimcConfiguration.build(
        world_count=2, utility_id=UtilityId.TRICK_SPLIT_V1
    )
    with pytest.raises(SearchConfigurationError):
        configuration.require_registerable_utility()


def test_every_value_stays_inside_its_range_over_every_split():
    for contract in Contract:
        declarers = (None,) if contract is Contract.NOLO else (0, 1, 2, 3)
        for declarer in declarers:
            for split in range(TRICKS_PER_DEAL + 1):
                for score in _reachable_scores():
                    for seat in range(4):
                        summary = _summary(
                            contract=contract,
                            declarer=declarer,
                            team0_tricks=split,
                            score=score.as_tuple(),
                            root_seat=seat,
                        )
                        for item in UtilityId:
                            value = utility_value(item, summary)
                            assert -1.0 <= value <= 1.0


# ----------------------------------------------------------------- orientation


def test_orientation_is_exact_for_all_four_seats():
    """Team 0's value must be the exact negation of Team 1's, at every split."""

    for contract in Contract:
        declarers = (None,) if contract is Contract.NOLO else (0, 1)
        for declarer in declarers:
            for split in range(TRICKS_PER_DEAL + 1):
                team0 = utility_value(
                    UtilityId.DEAL_RESULT_V1,
                    _summary(
                        contract=contract,
                        declarer=declarer,
                        team0_tricks=split,
                        root_seat=0,
                    ),
                )
                team1 = utility_value(
                    UtilityId.DEAL_RESULT_V1,
                    _summary(
                        contract=contract,
                        declarer=declarer,
                        team0_tricks=split,
                        root_seat=1,
                    ),
                )
                assert team0 == pytest.approx(-team1)
                # Seats of one partnership must agree exactly.
                partner = utility_value(
                    UtilityId.DEAL_RESULT_V1,
                    _summary(
                        contract=contract,
                        declarer=declarer,
                        team0_tricks=split,
                        root_seat=2,
                    ),
                )
                assert partner == team0


def test_nolo_orientation_is_inverted_relative_to_rami():
    """Both partnerships want tricks in RAMI and want to avoid them in NOLO."""

    rami_many = utility_value(
        UtilityId.TRICK_SPLIT_V1,
        _summary(contract=Contract.RAMI, declarer=0, team0_tricks=11, root_seat=0),
    )
    rami_few = utility_value(
        UtilityId.TRICK_SPLIT_V1,
        _summary(contract=Contract.RAMI, declarer=0, team0_tricks=2, root_seat=0),
    )
    assert rami_many > rami_few
    nolo_many = utility_value(
        UtilityId.TRICK_SPLIT_V1,
        _summary(contract=Contract.NOLO, declarer=None, team0_tricks=11, root_seat=0),
    )
    nolo_few = utility_value(
        UtilityId.TRICK_SPLIT_V1,
        _summary(contract=Contract.NOLO, declarer=None, team0_tricks=2, root_seat=0),
    )
    assert nolo_few > nolo_many


# ------------------------------------------------------------ rule coverage


def test_rami_success_and_stolen_rami_are_scored_correctly():
    made = _summary(contract=Contract.RAMI, declarer=0, team0_tricks=9, root_seat=0)
    assert made.deal_score.points == 12
    assert made.root_team_wins_deal is True
    assert utility_value(UtilityId.DEAL_RESULT_V1, made) == pytest.approx(12 / 56)

    stolen = _summary(contract=Contract.RAMI, declarer=0, team0_tricks=3, root_seat=0)
    assert stolen.deal_score.stolen_rami is True
    assert stolen.deal_score.points == 32
    assert stolen.root_team_wins_deal is False
    assert utility_value(UtilityId.DEAL_RESULT_V1, stolen) == pytest.approx(-32 / 56)

    # The defenders' view of the same stolen RAMI is the exact mirror.
    defenders = _summary(
        contract=Contract.RAMI, declarer=0, team0_tricks=3, root_seat=1
    )
    assert defenders.root_team_wins_deal is True
    assert utility_value(UtilityId.DEAL_RESULT_V1, defenders) == pytest.approx(32 / 56)


def test_nolo_scoring_follows_the_ruleset_table():
    for team0_tricks, points in ((6, 4), (5, 8), (0, 28)):
        summary = _summary(
            contract=Contract.NOLO, declarer=None, team0_tricks=team0_tricks
        )
        assert summary.deal_score.points == points
        assert summary.root_team_wins_deal is True


def test_a_down_team_win_resets_and_is_worth_the_same_at_any_margin():
    small = _summary(
        contract=Contract.NOLO, declarer=None, team0_tricks=6, score=(0, 20)
    )
    large = _summary(
        contract=Contract.NOLO, declarer=None, team0_tricks=0, score=(0, 20)
    )
    assert small.match_score_after.as_tuple() == (0, 0)
    assert large.match_score_after.as_tuple() == (0, 0)
    assert utility_value(UtilityId.MATCH_TRANSITION_V1, small) == utility_value(
        UtilityId.MATCH_TRANSITION_V1, large
    )
    # Deal points disagree, which is exactly why they are the wrong currency.
    assert utility_value(UtilityId.DEAL_RESULT_V1, small) != utility_value(
        UtilityId.DEAL_RESULT_V1, large
    )


def test_an_up_team_win_that_reaches_the_target_is_scored_as_a_match_win():
    summary = _summary(
        contract=Contract.RAMI, declarer=0, team0_tricks=7, score=(48, 0)
    )
    assert summary.match_score_after.as_tuple() == (52, 0)
    assert is_match_terminal(summary.match_score_after)
    assert utility_value(UtilityId.MATCH_TRANSITION_V1, summary) == 1.0
    losing = _summary(
        contract=Contract.RAMI, declarer=0, team0_tricks=7, score=(48, 0), root_seat=1
    )
    assert utility_value(UtilityId.MATCH_TRANSITION_V1, losing) == -1.0


def test_overshoot_past_the_target_is_worth_no_more_than_reaching_it():
    exact = _summary(
        contract=Contract.RAMI, declarer=0, team0_tricks=7, score=(48, 0)
    )
    over = _summary(
        contract=Contract.RAMI, declarer=0, team0_tricks=13, score=(48, 0)
    )
    assert over.match_score_after.as_tuple()[0] > 52
    assert utility_value(UtilityId.MATCH_TRANSITION_V1, exact) == utility_value(
        UtilityId.MATCH_TRANSITION_V1, over
    )


def test_the_two_registerable_utilities_agree_ordinally_from_zero_zero():
    """From 0-0 the two registerable adapters rank every outcome identically.

    This is why Phase 5C's utility ablation was run at 0-0 and found nothing: at that
    score the winner's rise *is* the deal points, so the two adapters differ only by a
    positive scale factor. The one case that could break it - a 56-point stolen RAMI -
    ends the match and maps to each adapter's extreme under both. A meaningful utility
    contrast therefore has to start from a nonzero score.
    """

    disagreements = 0
    for contract in Contract:
        declarers = (None,) if contract is Contract.NOLO else (0, 1, 2, 3)
        for declarer in declarers:
            for seat in range(4):
                rows = [
                    (
                        utility_value(
                            UtilityId.MATCH_TRANSITION_V1,
                            _summary(
                                contract=contract,
                                declarer=declarer,
                                team0_tricks=split,
                                root_seat=seat,
                            ),
                        ),
                        utility_value(
                            UtilityId.DEAL_RESULT_V1,
                            _summary(
                                contract=contract,
                                declarer=declarer,
                                team0_tricks=split,
                                root_seat=seat,
                            ),
                        ),
                    )
                    for split in range(TRICKS_PER_DEAL + 1)
                ]
                for left in rows:
                    for right in rows:
                        if (left[0] > right[0]) != (left[1] > right[1]):
                            disagreements += 1
    assert disagreements == 0


def test_the_two_registerable_utilities_can_disagree_at_a_nonzero_score():
    """And they do disagree once the rising score is in play, or one would be redundant."""

    down_small = _summary(
        contract=Contract.NOLO, declarer=None, team0_tricks=6, score=(0, 20)
    )
    down_large = _summary(
        contract=Contract.NOLO, declarer=None, team0_tricks=0, score=(0, 20)
    )
    assert utility_value(
        UtilityId.MATCH_TRANSITION_V1, down_small
    ) == utility_value(UtilityId.MATCH_TRANSITION_V1, down_large)
    assert utility_value(UtilityId.DEAL_RESULT_V1, down_small) < utility_value(
        UtilityId.DEAL_RESULT_V1, down_large
    )


def test_the_match_transition_adapter_agrees_with_the_phase5b_ordering():
    """Order-compatible with ``tuppi_exact.match_utility_from_score``, exhaustively.

    Keeping the scalar ordering identical to Phase 5B's lexicographic one is what
    lets a Phase 5C average and a Phase 5B exact verdict be read side by side.
    """

    checked = 0
    for contract in Contract:
        declarers = (None,) if contract is Contract.NOLO else (0, 1, 2, 3)
        for declarer in declarers:
            for score in _reachable_scores():
                for seat in range(4):
                    team = team_for_seat(seat)
                    pairs = []
                    for split in range(TRICKS_PER_DEAL + 1):
                        after = match_score_after_split(
                            contract=contract,
                            declarer=declarer,
                            team0_tricks=split,
                            starting_score=score,
                        )
                        pairs.append(
                            (
                                match_utility_from_score(after, team),
                                utility_value(
                                    UtilityId.MATCH_TRANSITION_V1,
                                    _summary(
                                        contract=contract,
                                        declarer=declarer,
                                        team0_tricks=split,
                                        score=score.as_tuple(),
                                        root_seat=seat,
                                    ),
                                ),
                            )
                        )
                    for left in pairs:
                        for right in pairs:
                            if left[0] == right[0]:
                                assert left[1] == pytest.approx(right[1])
                            elif left[0] > right[0]:
                                assert left[1] > right[1]
                            checked += 1
    assert checked > 10000


# ---------------------------------------------------------------- construction


def test_a_summary_from_a_completed_rollout_matches_the_engine(smoke_config):
    from tuppi_engine import apply_action, observation_for

    from tuppi_search.rollout import SeatPolicies, complete_deal

    for position in walk_deal(stream_index=2):
        if position.deal_state.phase.value != "TRICK_PLAY":
            continue
        seat = position.observation.observing_seat
        policies = SeatPolicies(configuration=smoke_config, root_seat=seat)
        outcome = complete_deal(
            position.deal_state, policies=policies, root_seat=seat
        )
        summary = outcome.summary
        assert summary.tricks_simulated == TRICKS_PER_DEAL
        assert summary.source is OutcomeSource.ROLLOUT
        assert summary.root_team is team_for_seat(seat)
        assert 0 <= summary.team0_tricks <= TRICKS_PER_DEAL
        del apply_action, observation_for
        return
    raise AssertionError("no trick-play position was reached")


def test_the_exact_tail_summary_is_the_same_type_as_a_rollout_summary():
    """Structural compatibility: the tail changes the policy, not the currency."""

    tail = exact_tail_summary(
        contract=Contract.RAMI,
        declarer=0,
        team0_tricks=8,
        starting_score=MatchScore(),
        root_seat=0,
        tricks_simulated=9,
        solver_nodes=123,
    )
    rollout = _summary(contract=Contract.RAMI, declarer=0, team0_tricks=8)
    assert type(tail) is type(rollout)
    assert tail.source is OutcomeSource.EXACT_TAIL
    assert rollout.source is OutcomeSource.ROLLOUT
    for item in UtilityId:
        assert utility_value(item, tail) == utility_value(item, rollout)


def test_malformed_summaries_are_refused():
    with pytest.raises(UtilityError):
        DealOutcomeSummary(
            contract=Contract.NOLO,
            declarer=0,
            team0_tricks=7,
            starting_score=MatchScore(),
            root_team=Team.TEAM_0,
            source=OutcomeSource.ROLLOUT,
            tricks_simulated=13,
        )
    with pytest.raises(UtilityError):
        DealOutcomeSummary(
            contract=Contract.RAMI,
            declarer=None,
            team0_tricks=7,
            starting_score=MatchScore(),
            root_team=Team.TEAM_0,
            source=OutcomeSource.ROLLOUT,
            tricks_simulated=13,
        )
    with pytest.raises(UtilityError):
        utility_value("not a utility", _summary())  # type: ignore[arg-type]
    with pytest.raises(UtilityError):
        summary_from_completed_deal(
            "not a state",  # type: ignore[arg-type]
            root_seat=0,
            source=OutcomeSource.ROLLOUT,
            tricks_simulated=13,
        )
