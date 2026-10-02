"""Price show decisions with the real heuristic continuing, in the authoritative engine.

The native one-step prices (tools/heuristic_mining.py) let v2's clone, and
TuppiAI's sooli heuristics, play the rest of the deal. For showing they did not
reproduce the H1 game results. Here every show decision of v2 self-play is
branched in the authoritative engine: the actual game is v2's own choice, and
the other contract (with v2's own card for it) is played out by the same v2
agents with TuppiProject's sooli fallback, exactly as in `tuppi_ai.evaluate`.
delta = value(other contract) - value(v2's choice), for the acting team.

    python tools/show_true_price.py --deals 20000 --workers 4 --out runs/heuristic/show_true1.pkl
"""

from __future__ import annotations

import argparse
import gzip
import pickle
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

_W: dict = {}


def _init(seed: str, base: str) -> None:
    from tuppi_agents.sooli import SooliFallbackAgent

    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    from tuppi_ai.incumbent import incumbent_agents

    agents = incumbent_agents(base)
    _W["agents"], _W["wrapped"] = agents, {s: SooliFallbackAgent(a) for s, a in agents.items()}
    _W["equity"], _W["seed"] = Equity.load(EQUITY), seed


def _finish(state, dealer):
    """Play to the end of the deal with v2; the team-0 equity change."""
    from tuppi_engine import apply_match_action, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES

    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        state = apply_match_action(state, _W["wrapped"][seat].choose_action(match_observation_for(state, seat)))
    r = state.completed_deals[-1].public_result
    return _W["equity"].delta0(r.score_before.as_tuple(), r.score_after.as_tuple(), dealer)


def price(indices: list[int]) -> list[dict]:
    from heuristic_mining import _hand_features, _score, _show_id
    from tuppi_engine import (EnginePhase, ExplicitDeal, apply_match_action, begin_explicit_deal, create_match,
                              match_observation_for)
    from tuppi_engine.trusted import trusted_transitions
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    from tuppi_ai.bridge import engine_action, mask_of, obs_from_player_observation

    rows = []
    with trusted_transitions():
        for index in indices:
            rng = random.Random(f"{_W['seed']}|show|{index}")
            cards = list(FULL_DECK)
            rng.shuffle(cards)
            hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
            dealer, score = rng.randrange(4), _score(rng)
            state = begin_explicit_deal(
                create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="show-true",
                             ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=dealer, hands=hands))
            pending = []
            while state.phase is EnginePhase.SHOWING:
                seat = state.current_actor
                obs = match_observation_for(state, seat)
                dec = _W["agents"][seat].decide(obs, diagnostics=True)
                if len(obs.legal_actions) > 1:
                    sel = next(c for c in dec.diagnostics.candidates if c.selected)
                    other = [c for c in dec.diagnostics.candidates
                             if c.action["declared_contract"] != sel.action["declared_contract"]]
                    if other:
                        alt = _show_id(max(other, key=lambda c: tuple(c.score_vector)).action)
                        v_alt = _finish(apply_match_action(state, engine_action(alt, seat)), dealer)
                        row = {"deal": index, "seat": seat, "n_shows": int(obs_from_player_observation(obs).n_shows),
                               "heur_contract": sel.action["declared_contract"],
                               **_hand_features(mask_of(hands[seat]))}
                        pending.append((row, seat % 2, v_alt))
                state = apply_match_action(state, dec.action)
            v_main = _finish(state, dealer)
            for row, team, v_alt in pending:
                sign = 1.0 if team == 0 else -1.0
                d = sign * (v_alt - v_main)  # acting team: other contract minus v2's choice
                row["delta"] = d
                rows.append(row)
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--deals", type=int, default=20000)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--chunk", type=int, default=50)
    p.add_argument("--seed", default="show-true-v1")
    p.add_argument("--base", default=None, help="heuristic profile (default: the benchmark; run 1 used v2)")
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.base is None:
        from tuppi_ai.incumbent import INCUMBENT
        a.base = INCUMBENT
    chunks = [list(range(i, min(i + a.chunk, a.deals))) for i in range(0, a.deals, a.chunk)]
    t0, rows = time.time(), []
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(a.seed, a.base)) as pool:
        for i, part in enumerate(pool.map(price, chunks)):
            rows.extend(part)
            if (i + 1) % 40 == 0:
                print(f"{(i + 1) * a.chunk} deals, {len(rows)} show decisions, {time.time() - t0:.0f} s", flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(a.out, "wb") as f:
        pickle.dump({"rows": rows, "args": vars(a), "seconds": time.time() - t0}, f)
    print(f"{a.deals} deals, {len(rows)} show decisions in {time.time() - t0:.0f} s -> {a.out}")


if __name__ == "__main__":
    main()
