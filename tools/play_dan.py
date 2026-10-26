"""Terminal preview: human in seat 0, Dan in selected other seats. Local only."""
import argparse
import random
from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_rules import MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK
from tuppi_ai import native
from tuppi_ai.bridge import action_id
from tuppi_ai.dan import DanAgent
from tuppi_ai.lite import LiteAgent

def label(action):
    a = action_id(action)
    def card(c): return "23456789TJQKA"[c % 13] + "HDCS"[c // 13]
    if a < 52: return card(a)
    if a < 156:
        contract, c = divmod(a-52, 52)
        return ("NOLO " if contract == 0 else "RAMI ") + card(c)
    if a in (156, 157): return "Decline sooli" if a == 156 else "Accept sooli"
    return "Exchange " + card(a-158)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seed", default="dan-preview-v1")
    p.add_argument("--deals", type=int, default=3)
    p.add_argument("--dan-seats", default="1,3")
    a = p.parse_args()
    dan_seats = {int(s) for s in a.dan_seats.split(",") if s}
    if not dan_seats <= {1, 2, 3} or a.deals < 1:
        p.error("Dan seats must be among 1,2,3 and deals positive")
    native.set_parallel(False)
    agents = {s: DanAgent(s) if s in dan_seats else LiteAgent(s) for s in (1, 2, 3)}
    match = create_match(initial_score=MatchScore(0, 0), initial_dealer=3,
                         match_ref="dan-local-preview", ruleset_id=RulesetId.PROJECT_TARGET_V3)
    print("You are seat 0; partner 2. Card suits: H hearts, D diamonds, C clubs, S spades.")
    for deal in range(a.deals):
        cards = list(FULL_DECK)
        random.Random(f"{a.seed}|{deal}").shuffle(cards)
        match = begin_explicit_deal(match, ExplicitDeal(dealer=match.dealer,
            hands=tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))))
        print(f"\nDeal {deal+1}; score {match.score}")
        while match.phase in ACTIVE_PHASES:
            seat = match.current_actor
            obs = match_observation_for(match, seat)
            if seat == 0:
                print("\n" + " | ".join(f"{i+1}: {label(x)}" for i, x in enumerate(obs.legal_actions)))
                while True:
                    raw = input("Your action (q to stop): ").strip()
                    if raw.lower() == "q": return
                    if raw.isdigit() and 1 <= int(raw) <= len(obs.legal_actions):
                        action = obs.legal_actions[int(raw)-1]
                        break
            elif isinstance(agents[seat], DanAgent):
                decision = agents[seat].propose_action(obs)
                action = decision.action
            else:
                action = agents[seat].choose_action(obs)
            next_match = apply_match_action(match, action)
            if seat in dan_seats: agents[seat].commit_action(decision)
            print(f"{'You' if seat == 0 else 'Dan' if seat in dan_seats else 'Bot'} ({seat}): {label(action)}")
            match = next_match
        print(f"Score: {match.score}")
        if match.terminal: break

if __name__ == "__main__":
    main()
