"""Read-only package verification; capture originals before making a new preview."""
import hashlib
import json
import plistlib
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / "build-preview-v3"
ORIGINALS = [
    ROOT / "Tuppi.app",
    HERE / "build-preview-v2",
    ROOT / "audit_deliverables/tuppi_human_training_implementation_20261002/build-preview-v1",
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def original_hashes():
    return {
        str(file.relative_to(ROOT)): digest(file.read_bytes())
        for directory in ORIGINALS
        for file in sorted(directory.rglob("*"))
        if file.is_file()
    }


if sys.argv[1] == "capture":
    output = HERE / "original-artifacts-v3.json"
    with output.open("x") as stream:
        json.dump(original_hashes(), stream, indent=2)
    print("Captured original app and preview hashes.")
elif sys.argv[1] == "verify":
    originals = json.loads((HERE / "original-artifacts-v3.json").read_text())
    assert originals == original_hashes(), "Original artifacts changed"
    app = OUT / "Tuppi Training.app"
    plist_bytes = (app / "Contents/Info.plist").read_bytes()
    plist = plistlib.loads(plist_bytes)
    assert plist["CFBundleIdentifier"] == "fi.tuppi.client.trainingpreview"
    assert plist["CFBundleShortVersionString"] == "0.3.2"
    assert plist["CFBundleVersion"] == "26"
    assert plist["TuppiTrainingServerURL"] == "http://127.0.0.1:18768"
    assert plist["TuppiTrainingDataDirectory"] == str(
        ROOT / "audit_deliverables/tuppi_human_training_implementation_20261002/runtime/preview-user-data"
    )
    banks = list(app.rglob("rami-threshold-v1.json"))
    assert len(banks) == 1
    bank_bytes = banks[0].read_bytes()
    assert bank_bytes == (HERE / "rami-threshold-v1.json").read_bytes()
    assert bank_bytes == (ROOT / "TuppiClient-training/Sources/TuppiClient/Resources/ExpertTraining/rami-threshold-v1.json").read_bytes()
    cases = json.loads(bank_bytes)["cases"]
    assert len(cases) == len({case["familyID"] for case in cases}) == 40
    positions = Counter()
    bands = Counter()
    for case in cases:
        observation = case["observation"]
        position = (observation["observing_seat"] - observation["dealer"] + 3) % 4
        band = case["bidProbe"]["band"]
        positions[position] += 1
        bands[(position, band)] += 1
        assert observation["match_score"] == [0, 0]
        assert observation["ruleset_id"] == "project_target_v3"
        assert len(set(observation["own_hand"])) == 13
        hands = case["feedback"]["fullHands"]
        assert len(hands) == 4 and all(len(hand) == 13 for hand in hands)
        assert len({card for hand in hands for card in hand}) == 52
        assert observation["own_hand"] == hands[observation["observing_seat"]]
        assert case["bidProbe"]["ramiAction"] in observation["legal_actions"]
        assert case["bidProbe"]["noloAction"] in observation["legal_actions"]
        assert not observation["publicly_shown_cards"] and not observation["show_actions"]
        assert not observation["bids_locked"]
        assert not case["approvedForAssessment"] and not case["feedback"]["adjudicated"]
    assert positions == Counter({position: 10 for position in range(4)})
    assert bands == Counter({(position, band): 1 if band in (0, 5) else 2
                             for position in range(4) for band in range(6)})
    pilots = list(app.rglob("pilot-v1.json"))
    assert len(pilots) == 1
    assert pilots[0].read_bytes() == (
        ROOT / "TuppiClient-training/Sources/TuppiClient/Resources/ExpertTraining/pilot-v1.json"
    ).read_bytes()
    source_root = ROOT / "TuppiClient-training/Sources/TuppiClient"
    lab = (source_root / "ExpertDecisionLabView.swift").read_text()
    branch = (source_root / "ExpertTrainingBranchView.swift").read_text()
    assert "TimelineView" not in lab and "jäljellä" not in lab
    assert "onKeyPress(characters: .alphanumerics" in lab and "onKeyPress(characters: .alphanumerics" in branch
    assert "onKeyPress(keys: [.leftArrow, .rightArrow]" in lab and "onKeyPress(keys: [.leftArrow, .rightArrow]" in branch
    assert "keyboardShortcut(.defaultAction)" in lab and "keyboardShortcut(.defaultAction)" in branch
    assert "TrainingTableInput()" in lab and "TrainingTableInput()" in branch
    assert ".disabled(store.session?.mode.defersFeedback == true)" in (source_root / "TuppiClientApp.swift").read_text()
    binary_path = app / "Contents/MacOS" / plist["CFBundleExecutable"]
    binary = binary_path.read_bytes()
    assert b"Aloita RAMI-kynnyksen mittaus" in binary
    archive_path = OUT / "Tuppi-Training-macOS.zip"
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        for path in app.rglob("*"):
            if path.is_file():
                assert archive.read(str(path.relative_to(OUT))) == path.read_bytes()
    result = {
        "passed": True,
        "version": "0.3.2",
        "build": "26",
        "timer_ui_removed": True,
        "shared_game_keyboard_resolver": True,
        "cases": 40,
        "families": 40,
        "positions": [positions[position] for position in range(4)],
        "bank_sha256": digest(bank_bytes),
        "binary_sha256": digest(binary),
        "zip_sha256": digest(archive_path.read_bytes()),
        "bundled_starter_pilot_matches_source": True,
        "zip_matches_app": True,
        "original_artifacts_unchanged": True,
        "app": str(app),
        "manual_gui_validation": "not performed",
    }
    with (OUT / "PACKAGE_VERIFICATION.json").open("x") as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(result, indent=2))
else:
    raise SystemExit("Use capture or verify")
