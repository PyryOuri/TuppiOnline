"""The owner's anonymous once-a-minute usage line."""
from __future__ import annotations

import asyncio
import re

from tuppi_server.usage import QUIET_INTERVAL_SECONDS, Usage

from test_leaderboard import Room, short_matches  # noqa: F401  (fixture)


def test_a_played_match_is_counted_without_private_details(tmp_path):
    async def scenario():
        table = Room(tmp_path)
        boundary = table.boundary
        boundary.activity[table.room.code] = __import__("time").time()
        await table.play_out()
        line = boundary.usage_line()
        fields = dict(item.split("=", 1) for item in line.split()[2:])
        assert fields["started"] == "1" and fields["finished"] == "1"
        assert int(fields["moves"]) > 10 and int(fields["saves"]) > 10
        assert int(fields["record_kb_max"]) > 0 and "save_ms_max" in fields
        assert fields["in_play"] == "0" and fields["storage"] == "ok" and int(fields["rss_mb"]) > 0
        for private in (table.room.code, "Pyry", "Aino", table.host.token, table.guest.token):
            assert private not in line
        # Counters restart after each line; a finished match is not counted again.
        again = dict(item.split("=", 1) for item in boundary.usage_line(force=True).split()[2:])
        assert again["started"] == again["finished"] == again["moves"] == "0"
        # A rematch is a new match.
        await table.send(0, "rematch")
        await table.play_out()
        boundary.usage.observe_matches(table.rooms._rooms)
        assert boundary.usage.counts["started"] == boundary.usage.counts["finished"] == 1
    asyncio.run(scenario())


def test_quiet_servers_log_rarely_and_error_codes_are_sanitised():
    usage = Usage()
    assert usage.line({"connections": 0, "in_play": 0}, now=1000.0) is not None, "first line"
    assert usage.line({"connections": 0, "in_play": 0}, now=1060.0) is None, "idle: quiet"
    assert usage.line({"connections": 1, "in_play": 0}, now=1120.0) is not None, "someone connected"
    usage.error("stale"); usage.error("Expecting value: line 1 <Pyry>")
    line = usage.line({"connections": 0, "in_play": 0}, now=1180.0)
    assert "errors=other:1,stale:1" in line and "Pyry" not in line
    assert usage.line({"connections": 0, "in_play": 0}, now=1180.0 + QUIET_INTERVAL_SECONDS) is not None, "heartbeat"
    assert re.fullmatch(r"tuppi usage( [a-z_]+=\S+)+", line)
