from __future__ import annotations

import json
from pathlib import Path

from tuppi_engine import match_input_from_data, strict_json_load_file
from tuppi_ui_fixtures.exporter import export_bundle
from tuppi_ui_fixtures.validation import validate_bundle, validate_protocol_manifest


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples/engine/project_target_v1"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_export_contains_all_required_scenarios_and_checksums(tmp_path: Path) -> None:
    output = export_bundle(tmp_path / "bundle")
    validate_bundle(output)
    manifest = _json(output / "manifest.json")
    names = {item["name"] for item in manifest["scenarios"]}
    assert names == {
        "full_nolo",
        "successful_rami",
        "stolen_rami",
        "verbal_fallback",
        "no_eligible_show",
        "exact_52",
    }
    checksums = _json(output / "sha256sums.json")["files"]
    assert "manifest.json" in checksums
    assert "compatibility.json" in checksums
    assert "transport/cases.json" in checksums
    assert "transport/wire-recordings.json" in checksums
    for relative, digest in checksums.items():
        assert digest.startswith("sha256:")
        assert (output / relative).is_file()


def test_reconnect_recordings_use_the_live_raw_observation_shape(tmp_path: Path) -> None:
    output = export_bundle(tmp_path / "bundle", ("exact_52",))
    cases = _json(output / "transport/cases.json")["cases"]
    reconnect_names = {
        "reconnect_during_showing",
        "reconnect_during_trick",
        "reconnect_after_reset",
    }
    for case in cases:
        if case["name"] not in reconnect_names:
            continue
        observation = case["response"]["payload"]["observation"]
        assert isinstance(case["response"]["payload"]["completed_deals"], list)
        assert observation["schema_version"] == "tuppi.engine.player_observation.v1"
        assert "snapshot_index" not in observation
        assert "showing_ui_hints" not in observation


def test_protocol_manifest_covers_every_implemented_message() -> None:
    manifest = validate_protocol_manifest()
    assert {item["id"] for item in manifest["messages"]} == {
        "compatibility_result",
        "create_room_request",
        "create_room_result",
        "join_room_request",
        "join_room_result",
        "configure_room_request",
        "configure_room_result",
        "room_settings_request",
        "room_settings_result",
        "ready_request",
        "ready_result",
        "analysis_request",
        "analysis_result",
        "completed_deal_analysis_request",
        "completed_deal_analysis_result",
        "training_analysis_request",
        "training_analysis_result",
        "server_error",
        "hello",
        "hello_ack",
        "ws_compatibility_result",
        "lobby_snapshot",
        "ready",
        "match_update",
        "action_submission",
        "action_acknowledgement",
        "reconnect",
        "reconnect_result",
        "pause",
        "resume",
        "rematch",
        "client_options",
        "leaderboard_request",
        "leaderboard_result",
        "protocol_error",
        "ping",
        "pong",
    }


def test_seat_fixture_does_not_contain_opponent_hidden_hands(tmp_path: Path) -> None:
    output = export_bundle(tmp_path / "bundle", ("verbal_fallback",))
    match_input = match_input_from_data(
        strict_json_load_file(EXAMPLES / "verbal_fallback_match.json")
    )
    seat_zero = _json(output / "fixtures/verbal_fallback/seat-0.json")
    first_observation_text = json.dumps(
        seat_zero["snapshots"][0],
        sort_keys=True,
    )
    own_codes = {card.to_code() for card in match_input.deals[0].hands[0]}
    opponent_codes = {
        card.to_code()
        for hand in match_input.deals[0].hands[1:]
        for card in hand
    }
    assert all(code in first_observation_text for code in own_codes)
    assert not opponent_codes & set(
        code for code in opponent_codes if code in first_observation_text
    )


def test_showing_hints_cover_verbal_and_no_eligible_fallbacks(tmp_path: Path) -> None:
    output = export_bundle(
        tmp_path / "bundle",
        ("verbal_fallback", "no_eligible_show"),
    )
    verbal = _json(output / "fixtures/verbal_fallback/seat-0.json")
    no_eligible = _json(output / "fixtures/no_eligible_show/seat-1.json")
    verbal_hints = [
        hint
        for snapshot in verbal["snapshots"]
        for hint in snapshot["showing_ui_hints"]["actions"]
    ]
    no_eligible_hints = [
        hint
        for snapshot in no_eligible["snapshots"]
        for hint in snapshot["showing_ui_hints"]["actions"]
    ]
    assert any(item["fallback"] == "eligible_rank_fallback" for item in verbal_hints)
    assert any(item["verbal_required"] for item in verbal_hints)
    assert any(item["fallback"] == "no_eligible_rank_fallback" for item in no_eligible_hints)


def test_transport_recordings_include_required_failure_modes(tmp_path: Path) -> None:
    output = export_bundle(tmp_path / "bundle", ("exact_52",))
    cases = _json(output / "transport/cases.json")["cases"]
    names = {case["name"] for case in cases}
    assert names == {
        "reconnect_during_showing",
        "reconnect_during_trick",
        "reconnect_after_reset",
        "duplicate_submission",
        "stale_submission",
        "server_rejection",
        "protocol_mismatch",
    }
