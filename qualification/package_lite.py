"""Copy a minimal lite AI package after the full builder qualification passed."""
import hashlib
import json
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
ai = root / 'ai'
out = root / 'lite-ai'
qualification = json.loads((root / 'qualification/result.json').read_text())
assert qualification['passed'] and qualification['bot']['level'] == 'full'
assert [item['worlds'] for item in qualification['references']] == [128, 1024]
manifest = json.loads((ai / 'models/hosted-models.json').read_text())
model = 'vrpo3_final.lite.npz'
assert hashlib.sha256((ai / 'models' / model).read_bytes()).hexdigest() == manifest[model]
out.mkdir(exist_ok=False)
(out / 'tuppi_ai').mkdir()
for name in ('__init__.py', 'native.py', 'bridge.py', 'lite.py'):
    shutil.copyfile(ai / 'tuppi_ai' / name, out / 'tuppi_ai' / name)
(out / 'native').mkdir()
shutil.copyfile(ai / 'native/libtuppi.so', out / 'native/libtuppi.so')
(out / 'models').mkdir()
shutil.copyfile(ai / 'models' / model, out / 'models' / model)
equity = 'equity_incumbent.json'
assert hashlib.sha256((ai / 'models' / equity).read_bytes()).hexdigest() == manifest[equity]
shutil.copyfile(ai / 'models' / equity, out / 'models' / equity)
(out / 'models/hosted-models.lite.json').write_text(json.dumps({name: manifest[name] for name in (model, equity)}, indent=2) + '\n')
print(json.dumps({'lite_package': str(out), 'model_sha256': manifest[model]}))
