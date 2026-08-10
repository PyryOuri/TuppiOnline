from __future__ import annotations

import json

import pytest

from tuppi_server.persistence import PersistenceError
from tuppi_server.rooms import RoomError, RoomManager


def test_solo_room_starts_with_three_ai_seats() -> None:
    manager = RoomManager()
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    assert room.snapshot()["lifecycle"] == "configured"

    manager.mark_ready(code=room.code, token=host.token)
    assert room.lifecycle == "playing"
    assert room.runner is not None
    assert room.runner.current_actor == 0


def test_private_room_assigns_open_human_seats_and_requires_all_ready() -> None:
    manager = RoomManager()
    room, host = manager.create_room(display_name="Isäntä")
    _, guest = manager.join_room(code=room.code, display_name="Vierailija")

    manager.mark_ready(code=room.code, token=host.token)
    assert room.runner is None
    manager.mark_ready(code=room.code, token=guest.token)
    assert room.runner is None

    manager.set_ai_seats(
        code=room.code,
        host_token=host.token,
        ai_seats=frozenset({2, 3}),
    )
    manager.mark_ready(code=room.code, token=host.token)
    assert room.runner is not None


def test_room_does_not_expose_session_tokens_in_lobby_snapshot() -> None:
    manager = RoomManager()
    room, host = manager.create_room(display_name="Isäntä")
    snapshot = room.snapshot()
    assert host.token not in str(snapshot)

    with pytest.raises(RoomError, match="room_not_found"):
        manager.get("XXXXXX")


def test_file_persistence_restores_room_sessions_and_live_runner(tmp_path) -> None:
    manager = RoomManager(persistence_dir=tmp_path)
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    manager.mark_ready(code=room.code, token=host.token)

    restored_manager = RoomManager(persistence_dir=tmp_path)
    restored_room, restored_session = restored_manager.session(
        code=room.code,
        token=host.token,
    )
    assert restored_session.seat == 0
    assert restored_room.lifecycle == "playing"
    assert restored_room.runner is not None
    assert restored_room.runner.observation(0) == room.runner.observation(0)  # type: ignore[union-attr]


def test_host_bot_delay_is_persisted_and_locked_after_start(tmp_path) -> None:
    manager = RoomManager(persistence_dir=tmp_path)
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    manager.set_ai_action_delay(
        code=room.code,
        host_token=host.token,
        ai_action_delay_ms=1500,
    )
    assert room.snapshot()["ai_action_delay_ms"] == 1500
    restored = RoomManager(persistence_dir=tmp_path).get(room.code)
    assert restored.ai_action_delay_ms == 1500

    manager.mark_ready(code=room.code, token=host.token)
    with pytest.raises(RoomError, match="settings_locked"):
        manager.set_ai_action_delay(
            code=room.code,
            host_token=host.token,
            ai_action_delay_ms=1000,
        )


def test_bot_delay_accepts_only_supported_host_values() -> None:
    manager = RoomManager()
    room, host = manager.create_room(display_name="Isäntä")
    _, guest = manager.join_room(code=room.code, display_name="Vierailija")
    with pytest.raises(RoomError, match="host_required"):
        manager.set_ai_action_delay(
            code=room.code,
            host_token=guest.token,
            ai_action_delay_ms=1000,
        )
    with pytest.raises(RoomError, match="invalid_ai_action_delay"):
        manager.set_ai_action_delay(
            code=room.code,
            host_token=host.token,
            ai_action_delay_ms=1250,
        )


def test_tampered_persisted_room_fails_closed(tmp_path) -> None:
    manager = RoomManager(persistence_dir=tmp_path)
    room, host = manager.create_room(
        display_name="Pelaaja",
        ai_seats=frozenset({1, 2, 3}),
    )
    manager.mark_ready(code=room.code, token=host.token)
    path = tmp_path / f"room-{room.code}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["runner"]["public_events"] = data["runner"]["public_events"][:-1]
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(PersistenceError, match="recovery|persisted|replay"):
        RoomManager(persistence_dir=tmp_path)
