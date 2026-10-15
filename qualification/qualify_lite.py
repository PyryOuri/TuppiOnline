"""Qualify exact lite traces in the final filesystem, with no PyTorch installed."""
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import shutil
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'engine/src'), str(root / 'ai')]
assert importlib.util.find_spec('torch') is None, 'PyTorch must not be installed in the lite image'
assert not any(shutil.which(name) for name in ('cc', 'gcc', 'g++', 'make')), 'Compiler tools must stay in the build stage'
assert {p.name for p in (root / 'ai/models').iterdir()} == {'vrpo3_final.lite.npz', 'hosted-models.lite.json'}
assert {p.name for p in (root / 'ai/tuppi_ai').iterdir()} == {'__init__.py', 'native.py', 'bridge.py', 'lite.py'}
from tuppi_server.hosted import verify_bot_identity
from tuppi_ai.bridge import action_id
from tuppi_ai.lite import lite_agents
from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
from tuppi_engine.state import ACTIVE_PHASES
from tuppi_engine.trusted import trusted_transitions
from tuppi_rules import MatchScore, RulesetId
from tuppi_rules.cards import FULL_DECK

builder_path = root / 'qualification/builder-result.json'
builder = json.loads(builder_path.read_text())
assert builder['passed'] and builder['bot']['level'] == 'full'
assert [item['worlds'] for item in builder['references']] == [128, 1024]
reference_path = root / 'qualification/lite-reference.json'
reference = json.loads(reference_path.read_text())
assert reference['schema'] == 'tuppi.hosted.lite.reference.v1'
assert reference['cursor_encoding'] == 'unsigned-64-decimal-string'
assert len(reference['rows']) == 500
identity = verify_bot_identity('lite')
assert identity['native_sha256'] == builder['bot']['native_sha256']
assert identity['models_sha256'] == reference['models_sha256']
try:
    verify_bot_identity('full')
except RuntimeError as error:
    assert 'only the lite bot' in str(error)
else:
    raise AssertionError('The lite-only runtime must reject full mode')

agents = lite_agents()
phases = {}
started = time.perf_counter()
with trusted_transitions():
    for i, expected in enumerate(reference['rows']):
        rng = random.Random(f'lite-parity-v1|{i}')
        cards = list(FULL_DECK)
        rng.shuffle(cards)
        hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
        cell = rng.randrange(25)
        score = (4 * cell, 0) if cell <= 12 else (0, 4 * (cell - 12))
        state = begin_explicit_deal(create_match(initial_score=MatchScore(*score), initial_dealer=i % 4,
            match_ref='lite-parity', ruleset_id=RulesetId.PROJECT_TARGET_V3), ExplicitDeal(dealer=i % 4, hands=hands))
        trace = []
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            obs = match_observation_for(state, seat)
            action = agents[seat].choose_action(obs)
            phase = obs.phase.value
            phases[phase] = phases.get(phase, 0) + 1
            trace.append([phase, action_id(action)])
            state = apply_match_action(state, action)
        actual = {'deal': i, 'trace': trace, 'cursors': [str(agents[s].rng.value) for s in range(4)]}
        assert actual == expected, f'Lite actions or controller cursors changed at deal {i}'
assert 'torch' not in sys.modules
report = {'passed': True, 'platform': sys.platform, 'bot': identity, 'references': builder['references'],
    'lite': {'deals': 500, 'decisions': sum(phases.values()), 'phases': phases,
        'exact_actions_and_cursors': True, 'torch_installed': False, 'torch_imported': False,
        'compiler_tools_present': False, 'elapsed_seconds': time.perf_counter() - started,
        'reference_sha256': hashlib.sha256(reference_path.read_bytes()).hexdigest()},
    'builder_qualification_sha256': hashlib.sha256(builder_path.read_bytes()).hexdigest(),
    'scope': 'Final lite-only image: frozen 500-deal exact parity plus separately qualified full build; no strength or host-capacity claim'}
(root / 'qualification/result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
