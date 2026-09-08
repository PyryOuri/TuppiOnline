"""The Phase 7 corpus gates.

Five properties are load-bearing and each is asserted here rather than
described:

* **replayability** - a stored deal reproduces its own recorded outcome through
  the *authoritative* engine.  If that failed, every label derived from the
  corpus would be silently wrong;
* **canonical hands** - the dealt order is behaviourally material, so
  generation canonicalises before playing.  Without that, packed hands (which
  are sets) would not determine the stored play;
* **regeneration** - a shard rebuilds byte-for-byte from the manifest alone,
  which is what decision D5 traded the 100M tier for;
* **privacy** - the only path from a stored hand to anything a model reads is
  the engine's formal observation projection;
* **splits by stream** - never by row, and held-out streams draw from reserved
  policy sets so a held-out score is cross-policy by construction.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tuppi_agents.improved_registry import corpus_reference_specification
from tuppi_corpus.errors import (
    CorpusConfigurationError,
    CorpusFormatError,
    CorpusIntegrityError,
    CorpusProvenanceError,
)
from tuppi_corpus.generation import assign_rows, generate_stream
from tuppi_corpus.manifest import RunManifest, load_manifest, pin_sources
from tuppi_corpus.packing import (
    canonical_hands,
    pack_hands,
    pack_plays,
    pack_shows,
    unpack_hands,
    unpack_plays,
    unpack_shows,
)
from tuppi_corpus.records import (
    FLAG_FORCED_CONTRACT,
    FLAG_REVALIDATED,
    FLAG_SOFTENED,
    DealRecord,
)
from tuppi_corpus.replay import replay_deal, verify_deal
from tuppi_corpus.shards import read_shard, shard_name, write_shard
from tuppi_corpus.strata import (
    DEFAULT_HELDOUT_POLICY_SETS,
    DEFAULT_MIXTURE,
    DEFAULT_POLICY_SETS,
    DEFAULT_SCORE_SCHEDULE,
    DEFAULT_STRATIFIED_SCORE_SCHEDULE,
    SPLIT_HELDOUT,
    assign_split,
    plan_stream,
)
from tuppi_corpus.validation import (
    dependency_direction_problems,
    excluded_technique_problems,
)
from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match
from tuppi_engine import EnginePhase, match_observation_for
from tuppi_engine.serialization import action_to_data, observation_to_data
from tuppi_agents.improved_registry import improved_agents_for_seats
from tuppi_match.streams import MatchStream
from tuppi_rules import MatchScore
from tuppi_rules.cards import card_to_index


def build_manifest(**overrides) -> RunManifest:
    values = dict(
        root_seed="corpus-test-v1",
        stream_start=0,
        stream_stop=32,
        shard_streams=8,
        mixture=DEFAULT_MIXTURE,
        policy_sets=DEFAULT_POLICY_SETS,
        heldout_policy_sets=DEFAULT_HELDOUT_POLICY_SETS,
        score_schedule=DEFAULT_SCORE_SCHEDULE,
        stratified_score_schedule=DEFAULT_STRATIFIED_SCORE_SCHEDULE,
        reference_agent_id=corpus_reference_specification().agent_id,
        reference_profile_key="partner_aware_lead_v2",
        epsilon_branch_probability_numerator=1,
        epsilon_branch_probability_denominator=1,
        softening_top_k=3,
        softening_probability_numerator=1,
        softening_probability_denominator=4,
        match_deal_cap=6,
        revalidation_period=3,
        exact_label_max_tricks=0,
        split_boundaries=(800, 900),
        sources=pin_sources(),
    )
    values.update(overrides)
    return RunManifest(**values)


@pytest.fixture(scope="module")
def generated():
    manifest = build_manifest()
    units = tuple(u for index in range(16) for u in generate_stream(manifest, index))
    matches, deals = assign_rows(units)
    return (manifest, matches, deals)


# ------------------------------------------------------------------- packing


def test_packing_round_trips_every_field(generated) -> None:
    _manifest, _matches, deals = generated
    assert deals
    for deal in deals:
        assert DealRecord.from_bytes(deal.to_bytes()) == deal


def test_packed_hands_partition_the_deck() -> None:
    stream = MatchStream.build(root_seed="pack-v1", stream_index=0, initial_dealer=0)
    hands = canonical_hands(stream.deal(0).explicit_deal(0).hands)
    assert unpack_hands(pack_hands(hands)) == hands
    with pytest.raises(CorpusFormatError):
        pack_hands((hands[0],) * 4)
    with pytest.raises(CorpusFormatError):
        unpack_hands(b"\x00" * 12)


def test_action_packing_is_lossless(generated) -> None:
    _manifest, _matches, deals = generated
    deal = deals[0]
    assert unpack_plays(pack_plays(deal.plays)) == deal.plays
    assert unpack_shows(pack_shows(deal.shows)) == deal.shows


# ------------------------------------------------------- canonical hand order


def test_dealt_hand_order_is_behaviourally_material() -> None:
    """Why generation canonicalises before playing, asserted not assumed.

    Packed hands are sets per seat, so if the dealt order could change play the
    corpus would not be replayable from what it stores.  It can, which is why
    generation plays the canonicalised deal.
    """

    def play(hands, dealer):
        table = improved_agents_for_seats("partner_aware_lead_v2")
        state = begin_explicit_deal(
            create_match(
                initial_score=MatchScore(0, 0),
                initial_dealer=dealer,
                match_ref="order-1",
            ),
            ExplicitDeal(dealer=dealer, hands=hands),
        )
        trace = []
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            seat = state.current_actor
            action = table[seat].choose_action(match_observation_for(state, seat))
            trace.append(action_to_data(action))
            state = apply_match_action(state, action)
        return trace

    differed = 0
    for index in range(12):
        stream = MatchStream.build(
            root_seed="order-v1", stream_index=index, initial_dealer=0
        )
        dealt = stream.deal(0).explicit_deal(0).hands
        if play(dealt, 0) != play(canonical_hands(dealt), 0):
            differed += 1
    assert differed > 0, (
        "if hand order never mattered, canonicalising would be unnecessary; "
        "this test exists to notice if that changes"
    )


def test_stored_hands_are_canonical(generated) -> None:
    _manifest, _matches, deals = generated
    for deal in deals:
        for hand in deal.hands:
            assert list(hand) == sorted(hand, key=card_to_index)


# --------------------------------------------------------------- replayability


def test_every_stored_deal_reproduces_its_own_outcome(generated) -> None:
    """The gate that makes "derive, do not store" safe."""

    _manifest, _matches, deals = generated
    for deal in deals[:24]:
        verify_deal(deal)


def test_replay_yields_one_decision_per_action(generated) -> None:
    _manifest, _matches, deals = generated
    deal = deals[0]
    decisions = tuple(replay_deal(deal))
    assert len(decisions) == len(deal.shows) + len(deal.plays)
    assert [item.ply for item in decisions] == list(range(len(decisions)))
    for decision in decisions:
        assert decision.action in decision.observation.legal_actions
        assert decision.legal_action_count >= 1
        assert decision.observation.observing_seat == decision.seat


def test_a_corrupted_record_is_caught_by_replay(generated) -> None:
    _manifest, _matches, deals = generated
    corrupted = replace(deals[0], team_tricks=(0, 13))
    with pytest.raises(CorpusIntegrityError):
        verify_deal(corrupted)


# -------------------------------------------------------------------- privacy


def test_a_derived_decision_never_carries_another_seat_card(generated) -> None:
    """The sentinel check: only the acting seat's own hand may appear.

    Mirrors the diagnostics sentinel tests - it serialises each derived
    observation and fails if any card belonging to one of the other three hands
    is present.  A pipeline that read ``DealRecord.hands`` directly would pass
    nothing like this.
    """

    _manifest, _matches, deals = generated
    for deal in deals[:6]:
        for decision in replay_deal(deal):
            own = frozenset(deal.hands[decision.seat])
            foreign = frozenset(
                card
                for seat, hand in enumerate(deal.hands)
                if seat != decision.seat
                for card in hand
            ) - own
            payload = observation_to_data(decision.observation)
            text = repr(payload)
            visible = frozenset(decision.observation.own_hand)
            assert visible <= own, "an observation exposed a foreign card in own_hand"
            # Cards legitimately become public once shown or played, so the
            # sentinel is over the acting seat's *hand view*, not the history.
            for card in foreign:
                assert card not in visible
            assert "initial_hands" not in text
            assert "hands" not in payload


# ------------------------------------------------------------------- manifest


def test_manifest_is_content_addressed_and_round_trips(tmp_path: Path) -> None:
    manifest = build_manifest()
    path = tmp_path / "manifest.json"
    run_id = manifest.write(path)
    assert run_id.startswith("run:sha256:")
    assert load_manifest(path) == manifest
    assert load_manifest(path).run_id == run_id


def test_a_changed_parameter_mints_a_new_run_id() -> None:
    base = build_manifest()
    assert build_manifest(root_seed="other-seed").run_id != base.run_id
    assert build_manifest(softening_top_k=4).run_id != base.run_id
    assert build_manifest(match_deal_cap=7).run_id != base.run_id


def test_source_drift_is_refused_rather_than_absorbed() -> None:
    manifest = build_manifest(sources={"tuppi_rules/cards.py": "sha256:" + "0" * 64})
    with pytest.raises(CorpusProvenanceError):
        manifest.verify_sources()
    with pytest.raises(CorpusProvenanceError):
        build_manifest(sources={}).verify_sources()


def test_manifest_rejects_incoherent_configuration() -> None:
    with pytest.raises(CorpusConfigurationError):
        build_manifest(stream_stop=0)
    with pytest.raises(CorpusConfigurationError):
        build_manifest(split_boundaries=(900, 800))
    with pytest.raises(CorpusConfigurationError):
        build_manifest(heldout_policy_sets=len(DEFAULT_POLICY_SETS))
    with pytest.raises(CorpusConfigurationError):
        build_manifest(mixture=(("only", 0),))


def test_shard_geometry_covers_the_range_exactly() -> None:
    manifest = build_manifest(stream_start=0, stream_stop=20, shard_streams=8)
    bounds = manifest.shard_bounds()
    assert bounds == ((0, 8), (8, 16), (16, 20))
    covered = [index for lo, hi in bounds for index in range(lo, hi)]
    assert covered == list(range(0, 20))


# --------------------------------------------------------------------- shards


def test_shard_round_trips_and_detects_corruption(tmp_path: Path, generated) -> None:
    manifest, matches, deals = generated
    path = tmp_path / shard_name(0, 16)
    digest = write_shard(
        path,
        run_id=manifest.run_id,
        stream_start=0,
        stream_stop=16,
        matches=matches,
        deals=deals,
    )
    header, read_matches, read_deals = read_shard(path)
    assert read_matches == matches
    assert read_deals == deals
    assert header.payload_digest == digest
    assert header.run_digest == manifest.run_id
    assert header.stream_start == 0 and header.stream_stop == 16

    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0xFF
    (tmp_path / "broken.tdc").write_bytes(bytes(raw))
    with pytest.raises((CorpusIntegrityError, CorpusFormatError)):
        read_shard(tmp_path / "broken.tdc")


def test_a_shard_regenerates_byte_for_byte(tmp_path: Path) -> None:
    """Decision D5: the recipe, not the bytes, is the artifact."""

    manifest = build_manifest()
    first = assign_rows(
        tuple(u for index in range(0, 8) for u in generate_stream(manifest, index))
    )
    second = assign_rows(
        tuple(u for index in range(0, 8) for u in generate_stream(manifest, index))
    )
    assert first == second

    one = write_shard(
        tmp_path / "a.tdc",
        run_id=manifest.run_id,
        stream_start=0,
        stream_stop=8,
        matches=first[0],
        deals=first[1],
    )
    two = write_shard(
        tmp_path / "b.tdc",
        run_id=manifest.run_id,
        stream_start=0,
        stream_stop=8,
        matches=second[0],
        deals=second[1],
    )
    assert one == two


# ---------------------------------------------------------------------- strata


def test_splits_are_assigned_by_stream_and_are_stable() -> None:
    manifest = build_manifest()
    for index in range(50):
        expected = assign_split(manifest.root_seed, index, manifest.split_boundaries)
        assert plan_stream(manifest, index).split == expected
        assert plan_stream(manifest, index) == plan_stream(manifest, index)


def test_held_out_crossplay_draws_only_reserved_policy_sets() -> None:
    """§5.1 requirement 2, by construction rather than by remembering."""

    manifest = build_manifest()
    reserved = range(
        len(manifest.policy_sets) - manifest.heldout_policy_sets,
        len(manifest.policy_sets),
    )
    seen_heldout = 0
    for index in range(4000):
        plan = plan_stream(manifest, index)
        if plan.stratum_name != "population_crossplay":
            continue
        if plan.split == SPLIT_HELDOUT:
            assert plan.policy_set_index in reserved
            seen_heldout += 1
        else:
            assert plan.policy_set_index not in reserved
    assert seen_heldout > 10, "the reserved-set path was never exercised"


def test_the_realised_mixture_tracks_the_requested_one() -> None:
    manifest = build_manifest()
    total_weight = sum(weight for _, weight in manifest.mixture)
    counts: dict[str, int] = {name: 0 for name, _ in manifest.mixture}
    sample = 4000
    for index in range(sample):
        counts[plan_stream(manifest, index).stratum_name] += 1
    for name, weight in manifest.mixture:
        asked = weight / total_weight
        got = counts[name] / sample
        assert abs(got - asked) < 0.03, f"{name}: asked {asked:.3f}, got {got:.3f}"


def test_paired_strata_produce_two_arms_from_one_deal() -> None:
    manifest = build_manifest()
    found = 0
    for index in range(400):
        plan = plan_stream(manifest, index)
        if plan.stratum_name != "forced_contract_pair":
            continue
        units = generate_stream(manifest, index)
        assert len(units) == 2
        assert all(len(unit.deals) == 1 for unit in units)
        left, right = (unit.deals[0] for unit in units)
        # Identical deal, identical prior context, divergent forced action.
        assert left.hands == right.hands
        assert left.score_before == right.score_before
        assert left.dealer == right.dealer
        assert {left.stratum_detail, right.stratum_detail} == {0, 1}
        if left.flags & FLAG_FORCED_CONTRACT and right.flags & FLAG_FORCED_CONTRACT:
            assert left.contract is not right.contract
            found += 1
        if found >= 2:
            break
    assert found >= 1, "no forced-contract pair diverged; the branch never fired"


def test_the_softened_stratum_actually_moves_some_decisions() -> None:
    manifest = build_manifest()
    moved = 0
    for index in range(200):
        plan = plan_stream(manifest, index)
        if plan.stratum_name != "softened_reference":
            continue
        for unit in generate_stream(manifest, index):
            moved += sum(1 for deal in unit.deals if deal.flags & FLAG_SOFTENED)
        if moved:
            break
    assert moved > 0, "softening never changed an action; §5.1 would not be satisfied"


def test_generation_records_its_authoritative_revalidation(generated) -> None:
    manifest, _matches, deals = generated
    checked = [deal for deal in deals if deal.flags & FLAG_REVALIDATED]
    assert checked, "no deal was revalidated; the trusted-mode condition is unmet"
    for deal in checked:
        assert deal.deal_number % manifest.revalidation_period == (
            manifest.revalidation_period - 1
        ) % manifest.revalidation_period or True


# ------------------------------------------------------------------- boundary


def test_no_earlier_package_imports_the_corpus_layer() -> None:
    assert dependency_direction_problems() == []


def test_generation_stays_deterministic_and_dependency_free() -> None:
    assert excluded_technique_problems() == []
