"""The Phase 5D-A corpus, convergence, and decomposition instruments."""

from __future__ import annotations

import json

import pytest

from tuppi_engine import DealState, EnginePhase, MatchState

from tuppi_search.convergence import (
    DEFAULT_BUDGETS,
    _spearman,
    evaluate_position,
    run_convergence,
)
from tuppi_search.corpus import (
    CorpusPosition,
    DealStage,
    DecisionCorpus,
    FeasibleBand,
    Role,
    ScoreState,
    build_corpus,
    deal_stage,
    feasible_band,
    partner_holds_trick,
    role,
    score_state,
)
from tuppi_search.decomposition import (
    ShowingDisagreement,
    card_play_decomposition,
    classify_showing,
    rollout_mismatch,
    showing_decomposition,
)
from tuppi_search.diagnostics import observation_visible_card_codes
from tuppi_search.errors import SearchError
from tuppi_eval.serialization import content_digest

from .conftest import walk_deal


@pytest.fixture(scope="module")
def tiny_corpus() -> DecisionCorpus:
    """A deliberately small corpus: these tests check structure, not statistics."""

    return build_corpus(
        showing_target=6,
        trick_play_target=10,
        streams=4,
        deals_per_stream=1,
        score_states=((0, 0), (48, 0)),
    )


# ------------------------------------------------------------------- labels


def test_stratum_labels_are_derived_from_the_observation_alone():
    for position in walk_deal(stream_index=0):
        observation = position.observation
        assert deal_stage(observation) in tuple(DealStage)
        assert score_state(observation) in tuple(ScoreState)
        assert role(observation) in tuple(Role)
        assert isinstance(partner_holds_trick(observation), bool)


def test_feasible_bands_cover_the_whole_range():
    assert feasible_band(1) is FeasibleBand.DETERMINED
    assert feasible_band(2) is FeasibleBand.TINY
    assert feasible_band(12) is FeasibleBand.TINY
    assert feasible_band(13) is FeasibleBand.SMALL
    assert feasible_band(10**7) is FeasibleBand.LARGE
    assert feasible_band(10**20) is FeasibleBand.HUGE


def test_partner_holds_trick_uses_led_suit_only():
    """Off-suit cards cannot win, so a high discard must not count as winning."""

    seen_true = seen_false = 0
    for position in walk_deal(stream_index=2):
        observation = position.observation
        if not observation.current_trick:
            assert partner_holds_trick(observation) is False
            continue
        led = observation.current_trick[0].card.suit
        best = max(
            (
                play
                for play in observation.current_trick
                if play.card.suit is led
            ),
            key=lambda play: play.card.rank.value,
        )
        expected = best.seat == observation.partner_seat
        assert partner_holds_trick(observation) is expected
        seen_true += int(expected)
        seen_false += int(not expected)
    assert seen_true + seen_false > 0


def test_the_stage_boundaries_are_the_documented_ones():
    from tuppi_engine import observation_for

    for position in walk_deal(stream_index=0):
        state = position.deal_state
        if state.phase is not EnginePhase.TRICK_PLAY:
            continue
        completed = len(state.completed_tricks)
        expected = (
            DealStage.EARLY
            if completed <= 3
            else (DealStage.MIDDLE if completed <= 8 else DealStage.LATE)
        )
        assert deal_stage(observation_for(state, state.current_actor)) is expected


# ------------------------------------------------------------------- corpus


def test_the_corpus_reaches_both_phases_and_records_provenance(tiny_corpus):
    assert len(tiny_corpus) == len(tiny_corpus.showing) + len(
        tiny_corpus.trick_play
    )
    assert tiny_corpus.showing and tiny_corpus.trick_play
    assert tiny_corpus.corpus_id.startswith("corpus:sha256:")
    for position in tiny_corpus.positions:
        assert position.position_id.startswith("pos:sha256:")
        assert position.stream_index >= 0
        assert position.decision_index >= 0
        assert position.legal_action_count >= 2
        assert position.feasible_assignment_count >= 1


def test_the_corpus_only_keeps_positions_with_a_real_choice(tiny_corpus):
    """A forced decision teaches nothing about search."""

    for position in tiny_corpus.positions:
        assert len(position.observation.legal_actions) >= 2


def test_the_corpus_position_exposes_no_engine_state(tiny_corpus):
    """The privacy boundary: an observation-only record, structurally."""

    for position in tiny_corpus.positions:
        for name in CorpusPosition.__slots__:
            value = getattr(position, name)
            assert not isinstance(value, (DealState, MatchState)), name


def test_the_corpus_summary_names_no_invisible_card(tiny_corpus):
    from tuppi_rules import FULL_DECK, card_to_code

    for position in tiny_corpus.positions:
        serialized = json.dumps(position.to_data(), sort_keys=True)
        visible = observation_visible_card_codes(position.observation)
        for card in FULL_DECK:
            code = card_to_code(card)
            if code in visible:
                continue
            assert f'"{code}"' not in serialized, (position.position_id, code)


def test_the_restricted_truth_is_a_separate_channel(tiny_corpus):
    position = tiny_corpus.positions[0]
    truth = tiny_corpus.restricted_truth(position.position_id)
    assert isinstance(truth.deal_state, DealState)
    assert truth.label == "perfect_information_restricted"
    # It is reachable only by an explicit lookup, never from the position itself.
    assert not hasattr(position, "deal_state")
    assert not hasattr(position, "truth")
    with pytest.raises(SearchError):
        tiny_corpus.restricted_truth("pos:sha256:" + "0" * 64)


def test_the_corpus_records_the_pimc_reference_disagreement(tiny_corpus):
    for position in tiny_corpus.positions:
        expected = position.pimc_action_id != position.reference_action_id
        assert position.pimc_disagrees_with_reference is expected


def test_the_corpus_summary_reports_stratum_counts(tiny_corpus):
    data = tiny_corpus.to_data()
    counts = data["stratum_counts"]
    for name in (
        "contract",
        "disagrees",
        "feasible_band",
        "phase",
        "role",
        "score_state",
        "stage",
    ):
        assert name in counts, name
        assert sum(counts[name].values()) == len(tiny_corpus)
    assert "restricted channel" in data["privacy_note"]


def test_the_corpus_is_reproducible():
    first = build_corpus(
        showing_target=3,
        trick_play_target=3,
        streams=2,
        deals_per_stream=1,
        score_states=((0, 0),),
    )
    again = build_corpus(
        showing_target=3,
        trick_play_target=3,
        streams=2,
        deals_per_stream=1,
        score_states=((0, 0),),
    )
    assert first.corpus_id == again.corpus_id
    assert [item.to_data() for item in first.positions] == [
        item.to_data() for item in again.positions
    ]


def test_corpus_worker_count_preserves_semantic_positions():
    arguments = dict(
        showing_target=3,
        trick_play_target=3,
        streams=2,
        deals_per_stream=1,
        score_states=((0, 0),),
    )
    serial = build_corpus(workers=1, **arguments)
    parallel = build_corpus(workers=8, **arguments)
    assert serial.corpus_id == parallel.corpus_id
    assert [item.to_data() for item in serial.positions] == [
        item.to_data() for item in parallel.positions
    ]


def test_corpus_report_reloads_without_serializing_restricted_truth():
    original = build_corpus(
        showing_target=3,
        trick_play_target=3,
        streams=2,
        deals_per_stream=1,
        score_states=((0, 0),),
    )
    report = original.to_data()
    report["positions"] = [item.to_data() for item in original.positions]
    serialized = json.dumps(report, sort_keys=True)
    assert "initial_hands" not in serialized
    assert "hands" not in serialized

    reloaded = DecisionCorpus.from_data(report)
    assert reloaded.corpus_id == original.corpus_id
    assert [item.to_data() for item in reloaded.positions] == [
        item.to_data() for item in original.positions
    ]
    assert [
        reloaded.restricted_truth(item.position_id).deal_state
        for item in reloaded.positions
    ] == [
        original.restricted_truth(item.position_id).deal_state
        for item in original.positions
    ]


def test_decomposition_worker_count_preserves_semantic_results(tiny_corpus):
    serial = (
        showing_decomposition(tiny_corpus, workers=1),
        card_play_decomposition(tiny_corpus, workers=1),
        rollout_mismatch(
            tiny_corpus, positions_limit=1, limit=2, workers=1
        ),
    )
    parallel = (
        showing_decomposition(tiny_corpus, workers=8),
        card_play_decomposition(tiny_corpus, workers=8),
        rollout_mismatch(
            tiny_corpus, positions_limit=1, limit=2, workers=8
        ),
    )
    assert [content_digest(item) for item in serial] == [
        content_digest(item) for item in parallel
    ]


def test_the_corpus_uses_a_fresh_development_bank():
    from tuppi_search.evaluation import (
        MATCH_COMPARISON_ROOT_SEED,
        phase5d_a_corpus_bank,
    )

    bank = phase5d_a_corpus_bank(stream_count=4)
    assert bank.role.value == "development"
    assert bank.supports_promotion is False
    assert bank.root_seed != MATCH_COMPARISON_ROOT_SEED


def test_the_corpus_rejects_malformed_targets():
    with pytest.raises(SearchError):
        build_corpus(showing_target=0, trick_play_target=1, streams=1)
    with pytest.raises(SearchError):
        build_corpus(showing_target=1, trick_play_target=0, streams=1)
    with pytest.raises(SearchError):
        build_corpus(
            showing_target=1, trick_play_target=1, streams=1, trick_play_per_deal=0
        )


def test_trick_play_positions_are_spread_across_distinct_deals():
    """A regression test for a corpus that came from a single set of hands.

    Filling the trick-play target in encounter order took all 96 positions of an
    earlier build from *one* deal, because one deal offers dozens of unforced card
    decisions. Position count then badly overstates the effective sample size, and
    every per-slice rate in the card-play decomposition describes one hand.
    """

    corpus = build_corpus(
        showing_target=8,
        trick_play_target=24,
        streams=16,
        deals_per_stream=1,
        trick_play_per_deal=3,
    )
    play = corpus.trick_play
    assert len(play) == 24
    per_hand: dict[tuple[int, int], int] = {}
    for position in play:
        key = (position.stream_index, position.deal_index)
        per_hand[key] = per_hand.get(key, 0) + 1
    assert max(per_hand.values()) <= 3, per_hand
    # 24 positions at no more than 3 per hand cannot come from fewer than 8 hands.
    assert len(per_hand) >= 8, per_hand


def test_kept_card_decisions_are_not_all_the_opening_ones():
    """The per-hand cap must not degenerate into 'always the first few tricks'."""

    corpus = build_corpus(
        showing_target=8,
        trick_play_target=40,
        streams=24,
        deals_per_stream=1,
        trick_play_per_deal=2,
    )
    stages = {position.stage for position in corpus.trick_play}
    assert {"early", "middle"} <= stages, stages


def test_each_hand_contributes_one_rotated_score_state():
    """Replaying identical hands at every score state buys cost, not information.

    ``score_state`` is *relative to the observing seat*, so one hand played at a
    lopsided score legitimately yields both ``up`` and ``down`` labels - one per team.
    What must hold is that a hand is played at a single match score: a level score
    labels every seat ``table``, and a lopsided one labels none of them, so no hand
    may mix ``table`` with the other two.
    """

    corpus = build_corpus(
        showing_target=16,
        trick_play_target=8,
        streams=12,
        deals_per_stream=1,
        score_states=((0, 0), (48, 0)),
    )
    by_hand: dict[tuple[int, int], set[str]] = {}
    for position in corpus.positions:
        key = (position.stream_index, position.deal_index)
        by_hand.setdefault(key, set()).add(position.score_state)
    assert by_hand, "the corpus sampled no position"
    for key, states in by_hand.items():
        level = states == {"table"}
        lopsided = states <= {"up", "down"}
        assert level or lopsided, (key, states)
    # Rotation must actually rotate: pooled over hands, both score states appear.
    pooled = {state for states in by_hand.values() for state in states}
    assert "table" in pooled, by_hand
    assert pooled & {"up", "down"}, by_hand


# -------------------------------------------------------------- convergence


def test_spearman_is_defined_only_for_comparable_orderings():
    assert _spearman(("a", "b", "c"), ("a", "b", "c")) == pytest.approx(1.0)
    assert _spearman(("a", "b", "c"), ("c", "b", "a")) == pytest.approx(-1.0)
    assert _spearman(("a",), ("a",)) is None
    assert _spearman(("a", "b"), ("a", "c")) is None


def test_nested_prefixes_are_used_so_budgets_share_worlds(tiny_corpus):
    """A change of action must be a change of opinion, not a different sample."""

    position = tiny_corpus.trick_play[0]
    result = evaluate_position(position, budgets=(2, 4, 8))
    assert [item.world_count for item in result.evaluations] == [2, 4, 8]
    # Unique-world counts can only grow as the prefix extends.
    counts = [item.unique_worlds for item in result.evaluations]
    assert counts == sorted(counts)
    for item in result.evaluations:
        assert item.action_id in {
            candidate for candidate in item.action_ranking
        }
        assert -1.0 <= item.mean_utility <= 1.0
        assert item.selection_gap >= 0.0


def test_convergence_requires_ascending_budgets(tiny_corpus):
    with pytest.raises(SearchError):
        evaluate_position(tiny_corpus.trick_play[0], budgets=(8, 2))


def test_convergence_reports_every_required_section(tiny_corpus):
    report = run_convergence(
        tiny_corpus, budgets=(2, 4), showing_limit=2, trick_play_limit=3
    )
    for key in (
        "adjacent_agreement",
        "agreement_with_largest",
        "by_stratum",
        "declaration_shift",
        "duplicate_fraction",
        "rank_correlation",
        "selection_gap",
        "timing_seconds",
    ):
        assert key in report, key
    assert report["positions"]["total"] == 5
    assert report["budgets"] == [2, 4]
    assert "not a strength evaluation" in report["interpretation"]
    for entry in report["agreement_with_largest"]:
        assert 0.0 <= entry["agreement_rate"] <= 1.0
    # The largest budget trivially agrees with itself.
    assert report["agreement_with_largest"][-1]["agreement_rate"] == 1.0


def test_convergence_worker_count_preserves_semantic_results(tiny_corpus):
    def semantic_id(report):
        semantic = dict(report)
        semantic.pop("timing_seconds")
        return content_digest(semantic)

    arguments = dict(
        budgets=(2, 4),
        showing_limit=1,
        trick_play_limit=1,
    )
    serial = run_convergence(tiny_corpus, workers=1, **arguments)
    parallel = run_convergence(tiny_corpus, workers=8, **arguments)
    assert semantic_id(serial) == semantic_id(parallel)


def test_convergence_default_budgets_are_the_documented_ladder():
    assert DEFAULT_BUDGETS == (2, 4, 8, 16, 32)


def test_convergence_refuses_an_empty_selection(tiny_corpus):
    with pytest.raises(SearchError):
        run_convergence(
            tiny_corpus, budgets=(2,), showing_limit=0, trick_play_limit=0
        )


# ------------------------------------------------------------ decomposition


def test_showing_classification_covers_every_case():
    from tuppi_rules import Contract, card_from_code, validate_show_action

    hand = tuple(
        card_from_code(code)
        for code in (
            "5H", "6H", "7H", "8H", "9H", "2D", "10D", "JD", "QD", "KD", "AD",
            "5C", "6C",
        )
    )
    rami_five = validate_show_action(
        seat=0, hand=hand, shown_card=card_from_code("5H"),
        declared_contract=Contract.RAMI, claimed_verbal_required=None,
    )
    rami_six = validate_show_action(
        seat=0, hand=hand, shown_card=card_from_code("6H"),
        declared_contract=Contract.RAMI, claimed_verbal_required=None,
    )
    nolo = validate_show_action(
        seat=0, hand=hand, shown_card=card_from_code("5C"),
        declared_contract=Contract.NOLO, claimed_verbal_required=None,
    )
    assert classify_showing(rami_five, rami_five) is ShowingDisagreement.SAME_ACTION
    assert (
        classify_showing(rami_five, rami_six)
        is ShowingDisagreement.SAME_CONTRACT_DIFFERENT_CARD
    )
    assert (
        classify_showing(rami_five, nolo)
        is ShowingDisagreement.PIMC_RAMI_REFERENCE_NOLO
    )
    assert (
        classify_showing(nolo, rami_five)
        is ShowingDisagreement.PIMC_NOLO_REFERENCE_RAMI
    )


def test_showing_decomposition_accounts_for_every_position(tiny_corpus):
    report = showing_decomposition(tiny_corpus)
    counts = report["classification_counts"]
    assert sum(counts.values()) == report["showing_positions"]
    assert sum(counts.values()) == len(tiny_corpus.showing)
    assert 0.0 <= report["pimc_rami_declaration_rate"] <= 1.0
    assert 0.0 <= report["reference_rami_declaration_rate"] <= 1.0
    assert report["rami_rate_difference"] == pytest.approx(
        report["pimc_rami_declaration_rate"]
        - report["reference_rami_declaration_rate"]
    )
    assert "Descriptive" in report["interpretation"]
    for bucket in report["by_showing_position"].values():
        assert sum(
            value for key, value in bucket.items() if key != "positions"
        ) == bucket["positions"]


def test_card_play_decomposition_slices_add_up(tiny_corpus):
    report = card_play_decomposition(tiny_corpus)
    assert report["trick_play_positions"] == len(tiny_corpus.trick_play)
    assert 0.0 <= report["disagreement_rate"] <= 1.0
    for name, values in report["by_slice"].items():
        if name == "overtakes_winning_partner":
            # Only defined where the partner currently holds the trick.
            continue
        assert sum(item["positions"] for item in values.values()) == (
            report["trick_play_positions"]
        ), name
    assert "not causes" in report["interpretation"]


def test_decomposition_refuses_a_corpus_without_the_needed_phase():
    only_play = build_corpus(
        showing_target=1,
        trick_play_target=4,
        streams=2,
        deals_per_stream=1,
        score_states=((0, 0),),
    )
    filtered = DecisionCorpus(
        positions=only_play.trick_play,
        truth=only_play.truth,
        bank_id=only_play.bank_id,
        reference_policy_key=only_play.reference_policy_key,
        pimc_profile_key=only_play.pimc_profile_key,
    )
    with pytest.raises(SearchError):
        showing_decomposition(filtered)


# --------------------------------------------------------- rollout mismatch


def test_rollout_mismatch_control_matches_perfectly(tiny_corpus):
    """The assumed continuation *is* reference play, so the control must match."""

    report = rollout_mismatch(tiny_corpus, positions_limit=3, limit=6)
    control = report["by_partner_kind"]["reference_partner"]
    assert control["mean_matched_fraction"] == pytest.approx(1.0)
    assert control["diverged_positions"] == 0


def test_rollout_mismatch_reports_the_other_designs(tiny_corpus):
    report = rollout_mismatch(tiny_corpus, positions_limit=3, limit=6)
    for kind in ("pimc_partner", "all_pimc"):
        stats = report["by_partner_kind"][kind]
        assert 0.0 <= stats["mean_matched_fraction"] <= 1.0
        assert stats["positions"] == 3
    assert report["label"] == "perfect_information_diagnostic"
    assert "cannot establish causality" in report["interpretation"]


def test_rollout_mismatch_records_contain_no_hidden_information(tiny_corpus):
    """Records may name seats and indices, never a card."""

    from tuppi_rules import FULL_DECK, card_to_code

    report = rollout_mismatch(tiny_corpus, positions_limit=3, limit=6)
    serialized = json.dumps(report["records"], sort_keys=True)
    for card in FULL_DECK:
        assert card_to_code(card) not in serialized
    for record in report["records"]:
        assert set(record) == {
            "assumed_actions",
            "contract",
            "first_divergence_index",
            "first_divergence_is_root_team",
            "first_divergence_seat",
            "matched_fraction",
            "matched_prefix",
            "partner_kind",
            "position_id",
            "stage",
        }


def test_rollout_mismatch_refuses_an_empty_selection(tiny_corpus):
    empty = DecisionCorpus(
        positions=tiny_corpus.showing,
        truth=tiny_corpus.truth,
        bank_id=tiny_corpus.bank_id,
        reference_policy_key=tiny_corpus.reference_policy_key,
        pimc_profile_key=tiny_corpus.pimc_profile_key,
    )
    with pytest.raises(SearchError):
        rollout_mismatch(empty, positions_limit=3)
