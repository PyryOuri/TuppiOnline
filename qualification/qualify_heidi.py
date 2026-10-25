"""Verify the named lite bots in the final, Torch-free product filesystem: Nelli 1.0
(heidi05, VRPO3) against heidi-reference.json and Nelli 1.1 (nelli11, the new base
network) against heidi12-reference.json, both Python LiteAgent C1H references."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'engine/src'), str(root / 'ai')]
assert importlib.util.find_spec('torch') is None
from tuppi_server.hosted_bot import HostedLiteAgent, lite_options
from tuppi_ai.bridge import action_id
from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK, card_to_index

assert lite_options() == 'off', 'New bot must remain opt-in'
assert HostedLiteAgent(1).checkpoint()['schema'] == 'tuppi.hosted.controller.lite.v1'
references = {'heidi05': (root / 'qualification/heidi-reference.json', 'v3'),
              'nelli11': (root / 'qualification/heidi12-reference.json', 'v4')}
cards_by_id = {card_to_index(card): card for card in FULL_DECK}
def split(value): return [value & 0xffffffff, value >> 32]
def cursors(agents):
    values = [agent.checkpoint() for agent in agents.values()]
    return [split(item['rng']) + [0] + split(item['gate_rng']) + split(item['belief_rng']) for item in values]
decisions = {}
with trusted_transitions():
    for bot, (reference, network) in references.items():
        cases = [test for test in json.loads(reference.read_text())['cases'] if test['bot'] == bot]
        assert len(cases) == 6, bot
        decisions[bot] = 0
        for test in cases:
            agents = {seat: HostedLiteAgent(seat, options='c1h', model=network) for seat in range(4)}
            for agent in agents.values(): agent.set_human_seats(test['humanSeats'])
            state = begin_explicit_deal(create_match(initial_score=MatchScore(*test['score']), initial_dealer=test['dealer'],
                match_ref='heidi-final-image', ruleset_id=RulesetId.PROJECT_TARGET_V3),
                ExplicitDeal(dealer=test['dealer'], hands=tuple(tuple(cards_by_id[card] for card in test['cards'][s*13:(s+1)*13]) for s in range(4))))
            assert cursors(agents) == test['context']
            for index, step in enumerate(test['steps']):
                seat = state.current_actor
                assert seat == step['seat']
                before = agents[seat].checkpoint()
                observation = match_observation_for(state, seat)
                action = agents[seat].choose_action(observation)
                assert action_id(action) == step['action']
                assert cursors(agents) == step['context']
                if index == 12:
                    restored = HostedLiteAgent(seat, options='c1h', model=network); restored.restore(before)
                    restored.set_human_seats(test['humanSeats'])
                    assert restored.choose_action(observation) == action
                    assert restored.checkpoint() == agents[seat].checkpoint()
                state = apply_match_action(state, action); decisions[bot] += 1
assert 'torch' not in sys.modules
report = {'passed': True, 'cases': {bot: 6 for bot in references}, 'decisions': decisions, 'three_rng_cursors_exact': True,
    'continuation_exact': True, 'default_options': 'off', 'torch_imported': False,
    'reference_sha256': {bot: hashlib.sha256(path.read_bytes()).hexdigest() for bot, (path, _) in references.items()},
    'scope': 'Nelli 1.0 (formerly Heidi 0.5) and Nelli 1.1 (the new base network) fixed final-image parity and continuation, '
             'not human strength or Render capacity'}
(root / 'qualification/heidi-result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
