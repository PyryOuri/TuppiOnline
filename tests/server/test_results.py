"""Anonymous match results for research on the bot against people."""
from __future__ import annotations

import asyncio
import json

import pytest
from tuppi_server import results as results_module
from tuppi_server.app import TuppiASGIApp
from tuppi_server.hosted import HostedBoundary
from tuppi_server.results import ResultRejected, Results, offline_row
from tuppi_server.rooms import RoomManager
from tuppi_ui_fixtures.validation import validate_instance

from .test_leaderboard import Room, short_matches  # noqa: F401  (fixture)

HTTP_SCHEMA = "https://example.invalid/tuppi/schemas/network/http_api.schema.json"
GOOD = {"conceded": 1, "deals": 9, "final_score": [56, 0], "id": "3f6c2a9e-7d41-4f0b-9a52-1c8e6b0d4a77",
        "winner_team": 0, "worlds": 128}


def test_offline_reports_are_validated(tmp_path):
    validate_instance(GOOD, f"{HTTP_SCHEMA}#/$defs/offlineResultRequest")
    row = offline_row(GOOD, day="2026-10-16")
    assert row == {"bot": "w128", "conceded": 1, "day": "2026-10-16", "deals": 9, "final_score": [56, 0],
                   "id": "offline-3f6c2a9e-7d41-4f0b-9a52-1c8e6b0d4a77", "source": "offline",
                   "team_humans": [1, 0], "winner_team": 0}
    for bad in ({**GOOD, "name": "Pyry"}, {**GOOD, "worlds": 64}, {**GOOD, "worlds": True},
                {**GOOD, "final_score": [56, 4]}, {**GOOD, "final_score": [40, 0]}, {**GOOD, "winner_team": 1},
                {**GOOD, "deals": 0}, {**GOOD, "conceded": 9}, {**GOOD, "id": "short"}, {**GOOD, "id": "../../x" * 3}, None):
        with pytest.raises(ResultRejected):
            offline_row(bad, day="2026-10-16")


def test_rows_are_counted_once_survive_restarts_and_stop_at_the_cap(tmp_path, monkeypatch):
    results = Results(tmp_path)
    assert results.record(offline_row(GOOD, day="2026-10-16"))
    assert not results.record(offline_row(GOOD, day="2026-10-17")), "a match is counted once"
    lost = offline_row({**GOOD, "id": "a" * 20, "winner_team": 1, "final_score": [0, 52], "worlds": 1024}, day="2026-10-16")
    assert results.record(lost)
    (tmp_path / "results.jsonl").open("a").write('{"torn": ')  # a crash mid-append
    again = Results(tmp_path)
    assert again.seen == results.seen
    assert again.summary()["totals"] == {"offline": {
        "w128": {"conceded_deals": 1, "deals": 9, "matches": 1, "people_wins": 1},
        "w1024": {"conceded_deals": 1, "deals": 9, "matches": 1, "people_wins": 0}}}
    monkeypatch.setattr(results_module, "MAX_RESULT_BYTES", again.bytes + 10)
    with pytest.raises(ResultRejected, match="results_full"):
        again.record(offline_row({**GOOD, "id": "b" * 20}, day="2026-10-16"))
    assert oct((tmp_path / "results.jsonl").stat().st_mode)[-3:] == "600"


def test_http_report_summary_origin_and_rate_limit(tmp_path):
    async def scenario():
        boundary = HostedBoundary(TuppiASGIApp(RoomManager(tmp_path)), origins={"https://tuppi.example"})

        async def call(method, path, body=None, origin=b"https://tuppi.example"):
            output = []
            async def receive():
                return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b"", "more_body": False}
            async def send(message): output.append(message)
            await boundary({"type": "http", "method": method, "path": path, "headers": [(b"origin", origin)]}, receive, send)
            return output[0]["status"], json.loads(output[1]["body"])

        assert await call("POST", "/v1/results", GOOD) == (200, {"recorded": True})
        assert await call("POST", "/v1/results", GOOD) == (200, {"recorded": False})
        assert await call("POST", "/v1/results", {**GOOD, "cards": [1, 2]}) == (400, {"error": "invalid_result"})
        assert (await call("POST", "/v1/results", GOOD, origin=b"https://evil.example"))[0] == 403
        status, summary = await call("GET", "/v1/results/summary")
        assert status == 200 and summary["totals"]["offline"]["w128"]["matches"] == 1
        assert boundary.usage.counts["results"] == 2
        statuses = [(await call("POST", "/v1/results", {**GOOD, "id": f"{i:020d}"}))[0] for i in range(30)]
        assert statuses.count(429) > 0, "reports are rate limited"
    asyncio.run(scenario())


def test_a_finished_online_match_is_recorded_without_names_or_codes(tmp_path):
    async def scenario():
        table = Room(tmp_path)
        await table.play_out()
        lines = (tmp_path / "results.jsonl").read_text().splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["source"] == "online" and row["team_humans"] == [2, 0] and row["deals"] >= 1
        assert row["final_score"][row["winner_team"]] >= 52
        for private in (table.room.code, table.room.code.lower(), "Pyry", "Aino", table.host.token):
            assert private not in lines[0]
        # A restart does not count it again.
        RoomManager(tmp_path)
        assert len((tmp_path / "results.jsonl").read_text().splitlines()) == 1
    asyncio.run(scenario())
