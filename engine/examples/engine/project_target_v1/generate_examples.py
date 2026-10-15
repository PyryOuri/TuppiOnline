"""Regenerate and validate the checked-in deterministic Phase 2 examples.

This developer utility writes only files beside itself.  It uses no randomness:
every hand and accepted action is explicitly constructed below.
"""

from __future__ import annotations

from pathlib import Path

from tuppi_engine import (
    ExplicitDeal,
    FixedScriptAgent,
    PlayCardAction,
    ShowAction,
)
from tuppi_engine.runner import run_match_input
from tuppi_engine.serialization import (
    ExplicitMatchInput,
    agent_script_to_data,
    atomic_write_canonical_json,
    match_input_to_data,
)
from tuppi_rules import Contract, MatchScore, card_from_code


OUTPUT_DIR = Path(__file__).resolve().parent
RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")


def card(code: str):
    return card_from_code(code)


def cards(*codes: str):
    return tuple(card(code) for code in codes)


def suit(suit_code: str):
    return tuple(card(f"{rank}{suit_code}") for rank in RANKS)


def show(seat: int, code: str, contract: Contract) -> ShowAction:
    return ShowAction(seat=seat, shown_card=card(code), declared_contract=contract)


def play(seat: int, code: str) -> PlayCardAction:
    return PlayCardAction(seat=seat, card=card(code))


def suit_block_hands():
    return (suit("H"), suit("D"), suit("C"), suit("S"))


def successful_rami_hands(*, leader: int, declarer: int, other_a: int, other_b: int):
    hands = [None, None, None, None]
    hands[leader] = cards(*(f"{rank}H" for rank in RANKS[:-1]), "2D")
    hands[declarer] = cards("AH", *(f"{rank}D" for rank in RANKS[1:]))
    hands[other_a] = suit("C")
    hands[other_b] = suit("S")
    return tuple(hands)


def successful_rami_plays(*, leader: int, declarer: int, other_a: int, other_b: int):
    actions = [
        play(leader, "2H"),
        play(declarer, "AH"),
        play(other_a, "2C"),
        play(other_b, "2S"),
    ]
    leader_cards = ("2D",) + tuple(f"{rank}H" for rank in RANKS[1:-1])
    for rank, leader_card in zip(RANKS[1:], leader_cards, strict=True):
        actions.extend(
            (
                play(declarer, f"{rank}D"),
                play(other_a, f"{rank}C"),
                play(other_b, f"{rank}S"),
                play(leader, leader_card),
            )
        )
    return tuple(actions)


def all_nolo_actions():
    actions = [
        show(1, "3D", Contract.NOLO),
        show(2, "3C", Contract.NOLO),
        show(3, "3S", Contract.NOLO),
        show(0, "3H", Contract.NOLO),
    ]
    for rank in RANKS:
        actions.extend(
            (
                play(1, f"{rank}D"),
                play(2, f"{rank}C"),
                play(3, f"{rank}S"),
                play(0, f"{rank}H"),
            )
        )
    return tuple(actions)


def stolen_rami_actions():
    actions = [show(0, "3H", Contract.RAMI)]
    for rank in RANKS:
        actions.extend(
            (
                play(3, f"{rank}S"),
                play(0, f"{rank}H"),
                play(1, f"{rank}D"),
                play(2, f"{rank}C"),
            )
        )
    return tuple(actions)


def verbal_fallback_hands():
    return (suit("C"), suit("H"), suit("D"), suit("S"))


def verbal_fallback_actions():
    actions = [show(0, "3C", Contract.RAMI)]
    for rank in RANKS:
        actions.extend(
            (
                play(3, f"{rank}S"),
                play(0, f"{rank}C"),
                play(1, f"{rank}H"),
                play(2, f"{rank}D"),
            )
        )
    return tuple(actions)


def no_eligible_hands():
    return (
        cards(*(f"{rank}H" for rank in RANKS[1:8]), *(f"{rank}D" for rank in RANKS[1:7])),
        cards(
            "2H", "10H", "JH", "QH", "KH", "AH",
            "2D", "10D", "JD", "QD", "KD", "AD", "2C",
        ),
        cards("9D", *(f"{rank}C" for rank in RANKS[1:])),
        suit("S"),
    )


def no_eligible_actions():
    # This is a fully materialized first-legal-in-original-hand transcript.
    raw_tricks = (
        ((0, "3H"), (1, "2H"), (2, "9D"), (3, "2S")),
        ((0, "4H"), (1, "10H"), (2, "3C"), (3, "3S")),
        ((1, "JH"), (2, "4C"), (3, "4S"), (0, "5H")),
        ((1, "QH"), (2, "5C"), (3, "5S"), (0, "6H")),
        ((1, "KH"), (2, "6C"), (3, "6S"), (0, "7H")),
        ((1, "AH"), (2, "7C"), (3, "7S"), (0, "8H")),
        ((1, "2D"), (2, "8C"), (3, "8S"), (0, "3D")),
        ((0, "9H"), (1, "10D"), (2, "9C"), (3, "9S")),
        ((0, "4D"), (1, "JD"), (2, "10C"), (3, "10S")),
        ((1, "QD"), (2, "JC"), (3, "JS"), (0, "5D")),
        ((1, "KD"), (2, "QC"), (3, "QS"), (0, "6D")),
        ((1, "AD"), (2, "KC"), (3, "KS"), (0, "7D")),
        ((1, "2C"), (2, "AC"), (3, "AS"), (0, "8D")),
    )
    return (show(1, "2H", Contract.RAMI),) + tuple(
        play(seat, code) for trick in raw_tricks for seat, code in trick
    )


def reset_deal_actions():
    actions = [
        show(2, "3C", Contract.NOLO),
        show(3, "3S", Contract.NOLO),
        show(0, "3H", Contract.NOLO),
        show(1, "3D", Contract.RAMI),
    ]
    for rank in RANKS:
        actions.extend(
            (
                play(0, f"{rank}H"),
                play(1, f"{rank}D"),
                play(2, f"{rank}C"),
                play(3, f"{rank}S"),
            )
        )
    return tuple(actions)


def twelve_trick_rami_hands():
    return (
        cards("AH", "2H", "2D", "3D", *(f"{rank}H" for rank in RANKS[2:11])),
        cards("3H", "KH", *(f"{rank}D" for rank in RANKS[2:])),
        suit("C"),
        suit("S"),
    )


def twelve_trick_rami_actions():
    actions = [
        show(0, "4H", Contract.NOLO),
        show(1, "4D", Contract.RAMI),
        play(0, "AH"),
        play(1, "3H"),
        play(2, "2C"),
        play(3, "2S"),
        play(0, "2H"),
        play(1, "KH"),
        play(2, "3C"),
        play(3, "3S"),
    ]
    seat0_discards = ("2D", "3D") + tuple(f"{rank}H" for rank in RANKS[2:11])
    for rank, discard in zip(RANKS[2:], seat0_discards, strict=True):
        actions.extend(
            (
                play(1, f"{rank}D"),
                play(2, f"{rank}C"),
                play(3, f"{rank}S"),
                play(0, discard),
            )
        )
    return tuple(actions)


def make_input(
    *,
    match_ref: str,
    initial_score: tuple[int, int],
    initial_dealer: int,
    deals: tuple[ExplicitDeal, ...],
) -> ExplicitMatchInput:
    return ExplicitMatchInput(
        match_ref=match_ref,
        initial_score=MatchScore(*initial_score),
        initial_dealer=initial_dealer,
        deals=deals,
    )


def validate_and_write(
    input_name: str,
    script_name: str,
    match_input: ExplicitMatchInput,
    actions: tuple,
    *,
    expected: tuple[tuple[int, int], bool, tuple[tuple[int, int], ...]],
) -> None:
    by_seat = tuple(
        tuple(action for action in actions if action.seat == seat) for seat in range(4)
    )
    result = run_match_input(
        match_input,
        tuple(FixedScriptAgent(script) for script in by_seat),
        require_complete_match=expected[1],
        expected_actions=actions,
    )
    final_score, terminal, trick_totals = expected
    actual_totals = tuple(item.public_result.team_tricks for item in result.deals)
    assert (result.final_score.team0, result.final_score.team1) == final_score
    assert result.terminal is terminal
    assert actual_totals == trick_totals
    atomic_write_canonical_json(OUTPUT_DIR / input_name, match_input_to_data(match_input))
    atomic_write_canonical_json(
        OUTPUT_DIR / script_name,
        agent_script_to_data(actions, match_input_id=match_input.match_input_id),
    )


def main() -> None:
    nolo_input = make_input(
        match_ref="example-all-nolo",
        initial_score=(0, 0),
        initial_dealer=0,
        deals=(ExplicitDeal(dealer=0, hands=suit_block_hands()),),
    )
    validate_and_write(
        "valid_one_deal_match.json",
        "full_nolo_script.json",
        nolo_input,
        all_nolo_actions(),
        expected=((28, 0), False, ((0, 13),)),
    )
    invalid_duplicate = match_input_to_data(nolo_input)
    invalid_duplicate["match_ref"] = "example-invalid-duplicate"
    # Replace AS with a second AH.  Hand lengths remain 13, so the loader's
    # complete-deck validation—not a superficial length check—rejects it.
    invalid_duplicate["deals"][0]["hands"][3][-1] = "AH"
    atomic_write_canonical_json(
        OUTPUT_DIR / "invalid_duplicate_card_deal.json", invalid_duplicate
    )

    rami_input = make_input(
        match_ref="example-successful-rami",
        initial_score=(0, 0),
        initial_dealer=0,
        deals=(
            ExplicitDeal(
                dealer=0,
                hands=successful_rami_hands(
                    leader=0, declarer=1, other_a=2, other_b=3
                ),
            ),
        ),
    )
    validate_and_write(
        "successful_rami_match.json",
        "successful_rami_script.json",
        rami_input,
        (show(1, "3D", Contract.RAMI),)
        + successful_rami_plays(leader=0, declarer=1, other_a=2, other_b=3),
        expected=((0, 28), False, ((0, 13),)),
    )

    stolen_input = make_input(
        match_ref="example-stolen-rami",
        initial_score=(0, 0),
        initial_dealer=3,
        deals=(ExplicitDeal(dealer=3, hands=suit_block_hands()),),
    )
    validate_and_write(
        "stolen_rami_match.json",
        "stolen_rami_script.json",
        stolen_input,
        stolen_rami_actions(),
        expected=((0, 56), True, ((0, 13),)),
    )

    verbal_input = make_input(
        match_ref="example-verbal-fallback",
        initial_score=(0, 0),
        initial_dealer=3,
        deals=(ExplicitDeal(dealer=3, hands=verbal_fallback_hands()),),
    )
    validate_and_write(
        "verbal_fallback_match.json",
        "verbal_fallback_script.json",
        verbal_input,
        verbal_fallback_actions(),
        expected=((0, 56), True, ((0, 13),)),
    )

    no_eligible_input = make_input(
        match_ref="example-no-eligible-show",
        initial_score=(0, 0),
        initial_dealer=0,
        deals=(ExplicitDeal(dealer=0, hands=no_eligible_hands()),),
    )
    validate_and_write(
        "no_eligible_show_match.json",
        "no_eligible_show_script.json",
        no_eligible_input,
        no_eligible_actions(),
        expected=((0, 12), False, ((4, 9),)),
    )

    exact_deals = (
        ExplicitDeal(
            dealer=0,
            hands=successful_rami_hands(
                leader=0, declarer=1, other_a=2, other_b=3
            ),
        ),
        ExplicitDeal(dealer=1, hands=suit_block_hands()),
        ExplicitDeal(
            dealer=2,
            hands=successful_rami_hands(
                leader=2, declarer=3, other_a=0, other_b=1
            ),
        ),
        ExplicitDeal(dealer=3, hands=twelve_trick_rami_hands()),
    )
    exact_actions = (
        (show(1, "3D", Contract.RAMI),)
        + successful_rami_plays(leader=0, declarer=1, other_a=2, other_b=3)
        + reset_deal_actions()
        + (show(3, "3D", Contract.RAMI),)
        + successful_rami_plays(leader=2, declarer=3, other_a=0, other_b=1)
        + twelve_trick_rami_actions()
    )
    exact_input = make_input(
        match_ref="example-exact-52",
        initial_score=(0, 0),
        initial_dealer=0,
        deals=exact_deals,
    )
    validate_and_write(
        "exact_52_match.json",
        "exact_52_script.json",
        exact_input,
        exact_actions,
        expected=((0, 52), True, ((0, 13), (13, 0), (0, 13), (1, 12))),
    )


if __name__ == "__main__":
    main()
