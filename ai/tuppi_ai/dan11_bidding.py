"""Cheap paired Dan 1.1 / Nelli 1.1 shadow-bid comparison under v3 rules."""
import random
from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_rules import Contract, MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK
from .bridge import action_id
from .dan import BOT_NAME, DanAgent
from .lite import LiteAgent, C1H, MODEL_V4


def observations(count, seed_start=0):
    for index in range(seed_start, seed_start+count):
        rng = random.Random(f"dan11-bidding-v1|{index}")
        cards = list(FULL_DECK)
        rng.shuffle(cards)
        level = rng.randrange(25)
        score = (0, 0) if level == 0 else (4*level, 0) if level <= 12 else (0, 4*(level-12))
        dealer = index % 4
        state = begin_explicit_deal(create_match(initial_score=MatchScore(*score), initial_dealer=dealer,
            match_ref=f"dan11-bid-{index}", ruleset_id=RulesetId.PROJECT_TARGET_V3),
            ExplicitDeal(dealer=dealer, hands=tuple(tuple(cards[s*13:(s+1)*13]) for s in range(4))))
        for position in range(4):
            obs = match_observation_for(state, state.current_actor)
            yield index, position+1, obs
            nolo = [a for a in obs.legal_actions if a.declared_contract is Contract.NOLO]
            if not nolo or position == 3:
                break
            state = apply_match_action(state, nolo[0])


def compare(count=1024, seed_start=0):
    if not 1 <= count <= 1024:
        raise ValueError("paired bid preview is capped at 1024 deals")
    dan = {s:DanAgent(s) for s in range(4)}
    nelli = {s:LiteAgent(s, options=C1H, model=MODEL_V4) for s in range(4)}
    rows = []
    for deal, position, obs in observations(count, seed_start):
        d = dan[obs.observing_seat].propose_action(obs)
        reference = action_id(nelli[obs.observing_seat].choose_action(obs))
        chosen = action_id(d.action)
        b = d.diagnostics["bidding"]
        assert b["nelli_action"] == reference
        assert not (reference < 104 and chosen >= 104)
        rows.append({"deal":deal, "position":position, "seat":obs.observing_seat,
            "score":[obs.match_score.team0, obs.match_score.team1], "nelli_action":reference,
            "dan_action":chosen, "gap":b["gap"], "reason":b["reason"]})
    n = sum(r["nelli_action"] >= 104 for r in rows)
    d = sum(r["dan_action"] >= 104 for r in rows)
    profile, runtime = dan[0].profile, dan[0].runtime
    for a in dan.values(): a.close()
    return {"schema":"tuppi.dan11.bidding.v1", "name":BOT_NAME, "reference":"Nelli 1.1",
        "profile":profile, "runtime":runtime, "seed_start":seed_start,
        "rami_margin":dan[0].config.rami_margin, "deals":count, "observations":len(rows),
        "shadow_prefix":"earlier seats legally forced NOLO; later bids are conditional shadow observations",
        "nelli_rami":n, "dan_rami":d, "vetoes":n-d, "extra_rami":0,
        "nelli_rate":n/len(rows), "dan_rate":d/len(rows), "rows":rows}
