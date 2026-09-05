#!/usr/bin/env python3
"""Drill your own past positions: choose, then see what was right.

Reading odds mostly helps after a decision is already made. Being asked to
commit to a card and only then shown the answer is the part that builds the
skill, so this deals you real positions from your own archive with the answer
hidden.

Three modes, aimed at what the archive says are the actual weaknesses:

``--leads``     Where you diverge most — 35% agreement with the reference on
                NOLO leads, mean rank 3.67, meaning the reference's fourth
                choice. Leads are also the one thing this project has proven:
                the void-seeking lead was worth -0.69 tricks and +13.9 points.
``--shows``     19% agreement, the largest gap of all, and the one decision in
                Tuppi that is not card play.
``--mistakes``  Positions where the Phase 5B solver proves the reference would
                have kept a trick you lost. Perfect information, so these are
                errors rather than opinions.

Default is a mix. Every position is one you actually played, and the reveal
names the exact optimum whenever the position is inside solver range.

Usage:
    python3 tools/drill.py [--leads|--shows|--mistakes] [--count N] [--seed S]
"""

from __future__ import annotations

import argparse
import random
import sys

import archive_replay


def describe_hand(hand, suit_order=None) -> str:
    from tuppi_rules import Suit

    order = suit_order or (Suit.SPADES, Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS)
    symbol = {Suit.SPADES: "S", Suit.HEARTS: "H", Suit.DIAMONDS: "D", Suit.CLUBS: "C"}
    names = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8", 9: "9",
             10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}
    parts = []
    for suit in order:
        ranks = sorted((c.rank.value for c in hand if c.suit is suit), reverse=True)
        if ranks:
            parts.append(f"{symbol[suit]}: " + " ".join(names[r] for r in ranks))
    return "   ".join(parts)


def position_lines(decision) -> list[str]:
    from tuppi_engine import EnginePhase
    from tuppi_rules import card_to_code

    deal = decision.deal
    lines = []
    if deal.phase is EnginePhase.SHOWING:
        lines.append("Phase: showing — declare RAMI or pass with NOLO")
        shown = [
            f"seat {a.seat} {a.declared_contract.value} ({card_to_code(a.shown_card)})"
            for a in deal.show_actions
        ]
        lines.append("Shows so far: " + (", ".join(shown) if shown else "none, you are first"))
    else:
        lines.append(f"Contract: {deal.contract.value}   trick {len(deal.completed_tricks) + 1}")
        trick = [f"seat {p.seat} {card_to_code(p.card)}" for p in deal.current_trick]
        lines.append("This trick: " + (", ".join(trick) if trick else "you lead"))
        lines.append(f"Tricks so far: {deal.team_tricks[0]} - {deal.team_tricks[1]}")
    return lines


def reveal(decision, policy):
    """What the reference picked, and what perfect play says where it can."""

    from tuppi_engine import PlayCardAction
    from tuppi_exact import SolverBudgetError, SolverError, solve_late_game
    from tuppi_rules import card_to_code

    ranking = policy.decide(decision.observation, diagnostics=False).scored
    lines = []
    ref = ranking.action
    ref_text = (
        card_to_code(ref.card)
        if isinstance(ref, PlayCardAction)
        else f"{ref.declared_contract.value} ({card_to_code(ref.shown_card)})"
    )
    played = decision.action
    played_text = (
        card_to_code(played.card)
        if isinstance(played, PlayCardAction)
        else f"{played.declared_contract.value} ({card_to_code(played.shown_card)})"
    )
    lines.append(f"  you played  : {played_text}")
    lines.append(f"  reference   : {ref_text}"
                 + ("   (agreed)" if ref == played else ""))

    if isinstance(played, PlayCardAction):
        try:
            solution = solve_late_game(decision.deal, maximum_tricks_remaining=4)
        except (SolverBudgetError, SolverError):
            solution = None
        if solution is not None:
            best = ", ".join(card_to_code(c) for c in solution.optimal_cards)
            regret = solution.regret_in_tricks(played.card)
            lines.append(f"  exact best  : {best}")
            lines.append(
                "  verdict     : optimal" if regret <= 0
                else f"  verdict     : cost {regret} trick(s) against perfect play"
            )
    return lines, ranking.action == played


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive")
    parser.add_argument("--leads", action="store_true")
    parser.add_argument("--shows", action="store_true")
    parser.add_argument("--mistakes", action="store_true")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    from tuppi_agents.void_lead import BASE_PROFILE_KEY, construct_void_lead_agent
    from tuppi_engine import EnginePhase, PlayCardAction
    from tuppi_exact import SolverBudgetError, SolverError, solve_late_game

    root = archive_replay.archive_root(args.archive)
    if not root.is_dir():
        print(f"No archive at {root}", file=sys.stderr)
        return 1

    policies = {s: construct_void_lead_agent(s, profile_key=BASE_PROFILE_KEY)
                for s in range(4)}
    pool = []
    for match in archive_replay.replay_archive(root):
        for decision in match.decisions:
            if not decision.is_human:
                continue
            deal = decision.deal
            if deal is None or len(decision.observation.legal_actions) < 2:
                continue
            showing = deal.phase is EnginePhase.SHOWING
            leading = not showing and not deal.current_trick
            if args.shows and not showing:
                continue
            if args.leads and not leading:
                continue
            if args.mistakes:
                if not isinstance(decision.action, PlayCardAction):
                    continue
                try:
                    solution = solve_late_game(deal, maximum_tricks_remaining=4)
                except (SolverBudgetError, SolverError):
                    continue
                if solution.regret_in_tricks(decision.action.card) <= 0:
                    continue
            pool.append(decision)

    if not pool:
        print("No positions matched. Try another mode, or play a few more deals.")
        return 1

    rng = random.Random(args.seed)
    rng.shuffle(pool)
    chosen = pool[: args.count]
    print(f"{len(pool)} positions available; drilling {len(chosen)}.\n"
          f"Type your card (e.g. QS), or RAMI / NOLO when showing. "
          f"Enter alone reveals, 'q' quits.\n")

    agreed = 0
    answered = 0
    for number, decision in enumerate(chosen, start=1):
        deal = decision.deal
        print(f"--- {number}/{len(chosen)} " + "-" * 46)
        for line in position_lines(decision):
            print(line)
        print("Your hand: " + describe_hand(deal.hands[decision.seat]))
        try:
            guess = input("your choice > ").strip()
        except EOFError:
            break
        if guess.lower() == "q":
            break
        lines, matched = reveal(decision, policies[decision.seat])
        if guess:
            answered += 1
            print(f"  you said    : {guess}")
        for line in lines:
            print(line)
        agreed += int(matched)
        print()

    print(f"Reviewed {len(chosen)} positions"
          + (f", answered {answered}" if answered else "")
          + f". You matched the reference in {agreed} of them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
