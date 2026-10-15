import hashlib
import json

import pytest

from tuppi_server.hosted import _verified_model_manifest


FULL = {'vrpo1_actor_0504.pt', 'vrpo3_final.pt', 'equity_incumbent.json', 'vrpo3_final.lite.npz'}


def write_manifest(root, names, filename):
    models = root / 'models'
    models.mkdir(exist_ok=True)
    manifest = {}
    for name in names:
        blob = name.encode()
        (models / name).write_bytes(blob)
        manifest[name] = hashlib.sha256(blob).hexdigest()
    (models / filename).write_text(json.dumps(manifest))
    return manifest


def test_lite_only_package_verifies_and_refuses_full_mode(tmp_path):
    expected = write_manifest(tmp_path, {'vrpo3_final.lite.npz'}, 'hosted-models.lite.json')
    assert _verified_model_manifest(tmp_path, 'lite') == expected
    with pytest.raises(RuntimeError, match='only the lite bot'):
        _verified_model_manifest(tmp_path, 'full')
    with pytest.raises(ValueError, match='lite or full'):
        _verified_model_manifest(tmp_path, 'fast')


def test_existing_full_package_stays_valid_for_both_levels(tmp_path):
    expected = write_manifest(tmp_path, FULL, 'hosted-models.json')
    assert _verified_model_manifest(tmp_path, 'full') == expected
    assert _verified_model_manifest(tmp_path, 'lite') == expected
    lite = write_manifest(tmp_path, {'vrpo3_final.lite.npz'}, 'hosted-models.lite.json')
    assert _verified_model_manifest(tmp_path, 'lite') == lite
    assert _verified_model_manifest(tmp_path, 'full') == expected


def test_corrupt_lite_manifest_cannot_fall_back_to_full(tmp_path):
    write_manifest(tmp_path, FULL, 'hosted-models.json')
    write_manifest(tmp_path, {'vrpo3_final.lite.npz'}, 'hosted-models.lite.json')
    (tmp_path / 'models/vrpo3_final.lite.npz').write_bytes(b'changed')
    with pytest.raises(RuntimeError, match='model identity mismatch'):
        _verified_model_manifest(tmp_path, 'lite')
    # Even if the full package could satisfy lite, a malformed lite declaration
    # fails rather than silently changing the package's identity boundary.
    (tmp_path / 'models/hosted-models.lite.json').write_text(json.dumps({'../other': '0' * 64}))
    with pytest.raises(RuntimeError, match='manifest fields'):
        _verified_model_manifest(tmp_path, 'lite')


def test_missing_or_invalid_lite_manifest_is_rejected(tmp_path):
    write_manifest(tmp_path, {'vrpo3_final.lite.npz'}, 'hosted-models.lite.json')
    model = tmp_path / 'models/vrpo3_final.lite.npz'
    model.unlink()
    with pytest.raises(FileNotFoundError):
        _verified_model_manifest(tmp_path, 'lite')
    (tmp_path / 'models/hosted-models.lite.json').write_text('[]')
    with pytest.raises(RuntimeError, match='manifest fields'):
        _verified_model_manifest(tmp_path, 'lite')
