#!/usr/bin/env python3
"""Regenerate the committed Phase 4 example and fixture artifacts.

Run from the repository root:

    PYTHONPATH=src python examples/agents/generate_examples.py

Every artifact is canonical JSON and is validated by ``tests/agents``. The
legacy compatibility fixture is the only artifact that reads the frozen
Archive, and it reads it as a historical oracle for deliberately compatible
positions only.
"""

from __future__ import annotations

from pathlib import Path
import sys

from tuppi_agents import (
    LADDER_PROFILE_KEYS,
    DiagnosticsRecordingAgent,
    construct_agent,
    phase4_agent_specifications,
    phase4_specifications_by_profile_key,
    phase4_team_specifications,
    profile_catalogue_to_data,
    rule_catalogue_to_data,
)
from tuppi_engine import (
    EnginePhase,
    ExplicitDeal,
    ShowAction,
    action_to_data,
    apply_match_action,
    atomic_write_canonical_json,
    begin_explicit_deal,
    create_match,
    match_observation_for,
    play_active_deal,
)
from tuppi_eval.deals import DealerPolicy, generate_deal_bank
from tuppi_eval.identities import agent_spec_to_data, team_spec_to_data
from tuppi_legacy.constants import ARTIFACT_ID, EMULATOR_SHA256
from tuppi_legacy.heuristic_oracle import (
    ORACLE_ID,
    TARGET_EQUIVALENT_BANNED_RANKS,
    legacy_play_choice,
    legacy_show_choice,
)
from tuppi_rules import MatchScore, card_to_code


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "examples" / "agents"

FIXTURE_SEED = 20260801
FIXTURE_DEALS = 6
DEMO_SEED = 1729


def _demo_deal():
    bank = generate_deal_bank(
        count=1,
        root_seed=DEMO_SEED,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"purpose": "phase4_example"},
    )
    return bank.base_deals[0]


def write_rule_catalogue() -> None:
    atomic_write_canonical_json(
        OUTPUT / "strategy_rule_catalogue.json", rule_catalogue_to_data()
    )


def write_profile_catalogue() -> None:
    atomic_write_canonical_json(
        OUTPUT / "heuristic_profiles.json", profile_catalogue_to_data()
    )


def write_agent_catalogue() -> None:
    atomic_write_canonical_json(
        OUTPUT / "phase4_agents.json",
        {
            "agents": [
                agent_spec_to_data(item) for item in phase4_agent_specifications()
            ],
            "ruleset_id": "project_target_v1",
            "schema_version": "tuppi.agents.agent_catalogue.v1",
            "teams": [
                {"name": name, **team_spec_to_data(team)}
                for name, team in sorted(phase4_team_specifications().items())
            ],
        },
    )


def write_ladder_deal() -> None:
    base = _demo_deal()
    rows = []
    for key in LADDER_PROFILE_KEYS:
        specification = phase4_specifications_by_profile_key()[key]
        agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
        state = create_match(
            initial_score=MatchScore(),
            initial_dealer=base.dealer,
            match_ref="phase4-example",
        )
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=base.dealer, hands=base.hands)
        )
        state = play_active_deal(state, agents)
        result = state.completed_deals[-1].public_result
        rows.append(
            {
                "agent_id": specification.agent_id,
                "contract": result.contract.value,
                "deal_points": result.deal_score.points,
                "declarer": result.declarer,
                "profile_key": key,
                "stolen_rami": result.deal_score.stolen_rami,
                "team_tricks": list(result.team_tricks),
                "winner_team": result.deal_score.winner_team.value,
            }
        )
    atomic_write_canonical_json(
        OUTPUT / "ladder_fixed_deal.json",
        {
            "base_deal_id": base.base_deal_id,
            "dealer": base.dealer,
            "deal_root_seed": DEMO_SEED,
            "hands": [[card_to_code(item) for item in hand] for hand in base.hands],
            "results": rows,
            "schema_version": "tuppi.agents.ladder_fixed_deal.v1",
            "starting_score": list(base.starting_score.as_tuple()),
        },
    )


def write_diagnostics_example() -> None:
    base = _demo_deal()
    specification = phase4_specifications_by_profile_key()["match_aware_v1"]
    wrappers = tuple(
        DiagnosticsRecordingAgent(construct_agent(specification, seat=seat))
        for seat in range(4)
    )
    state = create_match(
        initial_score=MatchScore(),
        initial_dealer=base.dealer,
        match_ref="phase4-diagnostics",
    )
    state = begin_explicit_deal(
        state, ExplicitDeal(dealer=base.dealer, hands=base.hands)
    )
    captured = []
    while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
        actor = state.current_actor
        assert actor is not None
        observation = match_observation_for(state, actor)
        action = wrappers[actor].choose_action(observation)
        if len(captured) < 3:
            captured.append(wrappers[actor].records[-1].to_data())
        state = apply_match_action(state, action)
    atomic_write_canonical_json(
        OUTPUT / "decision_diagnostics.json",
        {
            "base_deal_id": base.base_deal_id,
            "decisions": captured,
            "schema_version": "tuppi.agents.decision_diagnostics_bundle.v1",
        },
    )


def _fill_deck(fixed: dict[int, list[str]]) -> tuple[tuple, ...]:
    from tuppi_rules import FULL_DECK, card_from_code

    hands: dict[int, list] = {
        seat: [card_from_code(code) for code in fixed.get(seat, [])] for seat in range(4)
    }
    used = {item for hand in hands.values() for item in hand}
    for item in FULL_DECK:
        if item in used:
            continue
        seat = min(range(4), key=lambda index: (len(hands[index]), index))
        hands[seat].append(item)
    return tuple(tuple(hands[seat]) for seat in range(4))


# A curated hand with no eligible red rank 3-9 but a red ten, so both documented
# showing deviations are exercised on one position.
_DEVIATION_HAND = [
    "AH", "KH", "QH", "JH", "10H", "2H",
    "AD", "KD", "10D", "2D",
    "3C", "4C",
    "5S",
]


def build_deviation_positions() -> list[dict[str, object]]:
    """Record the showing positions where the two rule sets cannot agree."""

    from tuppi_legacy.constants import DEFAULT_SHOW_BANNED_RANKS

    specification = phase4_specifications_by_profile_key()["legacy_heuristic_port_v1"]
    hands = _fill_deck({1: _DEVIATION_HAND})
    agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
    state = create_match(
        initial_score=MatchScore(), initial_dealer=0, match_ref="phase4-deviation"
    )
    state = begin_explicit_deal(state, ExplicitDeal(dealer=0, hands=hands))
    actor = state.current_actor
    assert actor == 1
    observation = match_observation_for(state, actor)
    action = agents[actor].choose_action(observation)
    assert isinstance(action, ShowAction)
    target_equivalent = legacy_show_choice(observation)
    legacy_default = legacy_show_choice(
        observation, banned_ranks=tuple(DEFAULT_SHOW_BANNED_RANKS)
    )
    return [
        {
            "acting_seat": actor,
            "dealer": 0,
            "deviation": "legacy_cardless_verbal_declaration",
            "explanation": (
                "With legacy eligibility matched to project_target_v1 the frozen "
                "policy declares RAMI verbally with no card, which "
                "project_target_v1 cannot express; the port shows the lowest "
                "eligible off-colour card and derives verbal_required."
            ),
            "hands": [[card_to_code(item) for item in hand] for hand in hands],
            "legacy_banned_ranks": list(TARGET_EQUIVALENT_BANNED_RANKS),
            "legacy_card": (
                None
                if target_equivalent.card is None
                else card_to_code(target_equivalent.card)
            ),
            "legacy_contract": target_equivalent.contract.value,
            "legacy_verbal": target_equivalent.verbal,
            "port_action": action_to_data(action),
        },
        {
            "acting_seat": actor,
            "dealer": 0,
            "deviation": "legacy_show_rank_set_is_wider",
            "explanation": (
                "With the frozen default banned set {2, J, Q, K} the legacy policy "
                "shows a red ten. project_target_v1 restricts show ranks to 3-9, so "
                "the port cannot reproduce that card."
            ),
            "hands": [[card_to_code(item) for item in hand] for hand in hands],
            "legacy_banned_ranks": list(DEFAULT_SHOW_BANNED_RANKS),
            "legacy_card": (
                None if legacy_default.card is None else card_to_code(legacy_default.card)
            ),
            "legacy_contract": legacy_default.contract.value,
            "legacy_verbal": legacy_default.verbal,
            "port_action": action_to_data(action),
        },
    ]


def build_compatibility_fixture(*, deal_count: int, root_seed: int) -> dict[str, object]:
    """Curate positions where legacy and target semantics deliberately coincide.

    Every deal is played end to end by ``legacy_heuristic_port_v1``. At each
    decision the frozen ``HeuristicPolicy`` is asked the same question with the
    legacy banned-rank set configured so that show eligibility matches
    ``project_target_v1``. A position is marked compatible only when the two
    rule sets can express the same answer: a showing position where the frozen
    policy would have declared verbally without a card has no target equivalent
    and is recorded as a documented deviation instead.
    """

    specification = phase4_specifications_by_profile_key()["legacy_heuristic_port_v1"]
    bank = generate_deal_bank(
        count=deal_count,
        root_seed=root_seed,
        dealer_policy=DealerPolicy.ROUND_ROBIN,
        initial_dealer=0,
        starting_score=MatchScore(),
        creation_metadata={"purpose": "phase4_legacy_compatibility"},
    )
    deals: list[dict[str, object]] = []
    deviations: list[dict[str, object]] = []
    for base in bank.base_deals:
        agents = tuple(construct_agent(specification, seat=seat) for seat in range(4))
        state = create_match(
            initial_score=base.starting_score,
            initial_dealer=base.dealer,
            match_ref="phase4-compat",
        )
        state = begin_explicit_deal(
            state, ExplicitDeal(dealer=base.dealer, hands=base.hands)
        )
        sequence: list[dict[str, object]] = []
        positions: list[dict[str, object]] = []
        while state.phase in (EnginePhase.SHOWING, EnginePhase.TRICK_PLAY):
            actor = state.current_actor
            assert actor is not None
            observation = match_observation_for(state, actor)
            action = agents[actor].choose_action(observation)
            entry = {
                "acting_seat": actor,
                "action_prefix_length": len(sequence),
                "expected_action": action_to_data(action),
                "phase": state.phase.value,
            }
            if isinstance(action, ShowAction):
                choice = legacy_show_choice(observation)
                entry["legacy_contract"] = choice.contract.value
                entry["legacy_card"] = (
                    None if choice.card is None else card_to_code(choice.card)
                )
                entry["legacy_verbal"] = choice.verbal
                compatible = (
                    choice.contract is action.declared_contract
                    and not choice.verbal
                    and choice.card == action.shown_card
                )
                if not compatible and choice.verbal:
                    deviations.append(
                        {
                            "base_deal_id": base.base_deal_id,
                            "deviation": "legacy_cardless_verbal_declaration",
                            "position": entry["action_prefix_length"],
                        }
                    )
            else:
                legacy_card = legacy_play_choice(observation)
                entry["legacy_card"] = card_to_code(legacy_card)
                compatible = legacy_card == action.card
            entry["compatible"] = compatible
            positions.append(entry)
            sequence.append(action_to_data(action))
            state = apply_match_action(state, action)
        deals.append(
            {
                "action_sequence": sequence,
                "base_deal_id": base.base_deal_id,
                "dealer": base.dealer,
                "hands": [
                    [card_to_code(item) for item in hand] for hand in base.hands
                ],
                "positions": positions,
                "starting_score": list(base.starting_score.as_tuple()),
            }
        )
    total = sum(len(item["positions"]) for item in deals)
    agreed = sum(
        1
        for item in deals
        for position in item["positions"]
        if position["compatible"]
    )
    return {
        "compatible_position_count": agreed,
        "deals": deals,
        "deal_root_seed": root_seed,
        "deviation_positions": build_deviation_positions(),
        "documented_deviations": deviations,
        "equivalence_claim": (
            "Agreement is asserted only for the curated positions marked "
            "compatible, with the legacy banned-rank set configured to match "
            "project_target_v1 show eligibility. Complete behavioural "
            "equivalence across the two rule sets is not claimed."
        ),
        "legacy_artifact_id": ARTIFACT_ID,
        "legacy_emulator_sha256": EMULATOR_SHA256,
        "legacy_show_banned_ranks": list(TARGET_EQUIVALENT_BANNED_RANKS),
        "oracle_id": ORACLE_ID,
        "position_count": total,
        "ruleset_id": "project_target_v1",
        "schema_version": "tuppi.agents.legacy_compatibility_fixture.v1",
    }


def write_compatibility_fixture() -> None:
    fixture = build_compatibility_fixture(
        deal_count=FIXTURE_DEALS, root_seed=FIXTURE_SEED
    )
    atomic_write_canonical_json(
        OUTPUT / "legacy_port_compatibility.json", fixture
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    write_rule_catalogue()
    write_profile_catalogue()
    write_agent_catalogue()
    write_ladder_deal()
    write_diagnostics_example()
    write_compatibility_fixture()
    print(f"wrote Phase 4 example artifacts to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
