"""The two stored row types, and their fixed-width binary encodings.

A shard holds a match table and a deal table.  Both rows are fixed width so a
shard can be memory-mapped and indexed arithmetically, and so a decoder cannot
disagree with an encoder about where a field starts.

``DecisionRow`` is deliberately absent.  A decision is a pure function of a deal
plus a ply, so decisions are *derived* by replay (:mod:`tuppi_corpus.replay`)
and materialised only for subsets that are actually trained on.  Materialising
550M decision rows for a 10M-deal corpus would cost more than the deals do and
would pin the corpus to one encoder version.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

from tuppi_rules import Card, Contract

from .errors import CorpusFormatError
from .packing import (
    HANDS_BYTES,
    PLAYS_BYTES,
    SHOWS_BYTES,
    TRICK_WINNERS_BYTES,
    pack_hands,
    pack_plays,
    pack_shows,
    pack_trick_winners,
    unpack_hands,
    unpack_plays,
    unpack_shows,
    unpack_trick_winners,
)


RECORDS_SCHEMA_VERSION = "tuppi.corpus.records.v1"

#: No seat, no team, no pairing.  Distinct from seat 0 and team 0.
NONE_U8 = 0xFF
NONE_U16 = 0xFFFF
NONE_U32 = 0xFFFF_FFFF

_MATCH_STRUCT = struct.Struct("<IIIHHHHHBBBBBBB")
_DEAL_STRUCT = struct.Struct(
    f"<IHBBBBBBHHHHhhBBBBH{HANDS_BYTES}s{SHOWS_BYTES}s{PLAYS_BYTES}s"
    f"{TRICK_WINNERS_BYTES}sB"
)

MATCH_ROW_BYTES = _MATCH_STRUCT.size
DEAL_ROW_BYTES = _DEAL_STRUCT.size

#: Deal-record flag bits.
FLAG_VERBAL_REQUIRED = 1 << 0
FLAG_RESET = 1 << 1
FLAG_MATCH_TERMINAL = 1 << 2
FLAG_FORCED_CONTRACT = 1 << 3
FLAG_EPSILON_BRANCH = 1 << 4
FLAG_SOFTENED = 1 << 5
FLAG_REVALIDATED = 1 << 6
FLAG_FORCED_PLAY = 1 << 7


def _u8(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 0xFF:
        raise CorpusFormatError(f"{label} must fit in one unsigned byte")
    return value


def _u16(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 0xFFFF:
        raise CorpusFormatError(f"{label} must fit in two unsigned bytes")
    return value


def _u32(value: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 0xFFFF_FFFF:
        raise CorpusFormatError(f"{label} must fit in four unsigned bytes")
    return value


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """One complete match: its provenance, its length, and how it ended."""

    stream_index: int
    initial_dealer: int
    initial_score: tuple[int, int]
    final_score: tuple[int, int]
    deals_played: int
    winner_team: int | None
    termination: int
    stratum: int
    policy_set: int
    split: int
    pair_id: int | None
    first_deal_row: int

    def to_bytes(self) -> bytes:
        return _MATCH_STRUCT.pack(
            _u32(self.stream_index, "stream_index"),
            _u32(self.first_deal_row, "first_deal_row"),
            NONE_U32 if self.pair_id is None else _u32(self.pair_id, "pair_id"),
            _u16(self.initial_score[0], "initial_score[0]"),
            _u16(self.initial_score[1], "initial_score[1]"),
            _u16(self.final_score[0], "final_score[0]"),
            _u16(self.final_score[1], "final_score[1]"),
            _u16(self.deals_played, "deals_played"),
            _u8(self.initial_dealer, "initial_dealer"),
            NONE_U8 if self.winner_team is None else _u8(self.winner_team, "winner"),
            _u8(self.termination, "termination"),
            _u8(self.stratum, "stratum"),
            _u8(self.policy_set, "policy_set"),
            _u8(self.split, "split"),
            0,
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "MatchRecord":
        if len(payload) != MATCH_ROW_BYTES:
            raise CorpusFormatError(f"a match row is {MATCH_ROW_BYTES} bytes")
        (
            stream_index,
            first_deal_row,
            pair_id,
            initial0,
            initial1,
            final0,
            final1,
            deals_played,
            initial_dealer,
            winner,
            termination,
            stratum,
            policy_set,
            split,
            _reserved,
        ) = _MATCH_STRUCT.unpack(payload)
        return cls(
            stream_index=stream_index,
            initial_dealer=initial_dealer,
            initial_score=(initial0, initial1),
            final_score=(final0, final1),
            deals_played=deals_played,
            winner_team=None if winner == NONE_U8 else winner,
            termination=termination,
            stratum=stratum,
            policy_set=policy_set,
            split=split,
            pair_id=None if pair_id == NONE_U32 else pair_id,
            first_deal_row=first_deal_row,
        )


@dataclass(frozen=True, slots=True)
class DealRecord:
    """One deal: the hidden hands, the ordered actions, and the outcome.

    ``hands`` is research-private.  Everything a policy may see is derived from
    it by replaying through the engine's formal observation projection, never by
    reading this field; see :mod:`tuppi_corpus.replay` and the privacy test in
    ``tests/corpus/test_privacy.py``.
    """

    match_row: int
    deal_number: int
    dealer: int
    forehand: int
    contract: Contract
    declarer: int | None
    first_leader: int
    hands: tuple[tuple[Card, ...], ...]
    shows: tuple[tuple[Card, Contract], ...]
    plays: tuple[Card, ...]
    trick_winners: tuple[int, ...]
    team_tricks: tuple[int, int]
    deal_points: tuple[int, int]
    score_before: tuple[int, int]
    score_after: tuple[int, int]
    flags: int
    branch_ply: int | None
    stratum_detail: int

    def to_bytes(self) -> bytes:
        return _DEAL_STRUCT.pack(
            _u32(self.match_row, "match_row"),
            _u16(self.deal_number, "deal_number"),
            _u8(self.dealer, "dealer"),
            _u8(self.forehand, "forehand"),
            1 if self.contract is Contract.RAMI else 0,
            NONE_U8 if self.declarer is None else _u8(self.declarer, "declarer"),
            _u8(self.first_leader, "first_leader"),
            _u8(self.flags, "flags"),
            _u16(self.score_before[0], "score_before[0]"),
            _u16(self.score_before[1], "score_before[1]"),
            _u16(self.score_after[0], "score_after[0]"),
            _u16(self.score_after[1], "score_after[1]"),
            self.deal_points[0],
            self.deal_points[1],
            _u8(self.team_tricks[0], "team_tricks[0]"),
            _u8(self.team_tricks[1], "team_tricks[1]"),
            _u8(len(self.shows), "show_count"),
            _u8(self.stratum_detail, "stratum_detail"),
            NONE_U16 if self.branch_ply is None else _u16(self.branch_ply, "branch_ply"),
            pack_hands(self.hands),
            pack_shows(self.shows),
            pack_plays(self.plays),
            pack_trick_winners(self.trick_winners),
            0,
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "DealRecord":
        if len(payload) != DEAL_ROW_BYTES:
            raise CorpusFormatError(f"a deal row is {DEAL_ROW_BYTES} bytes")
        (
            match_row,
            deal_number,
            dealer,
            forehand,
            contract_bit,
            declarer,
            first_leader,
            flags,
            before0,
            before1,
            after0,
            after1,
            points0,
            points1,
            tricks0,
            tricks1,
            show_count,
            stratum_detail,
            branch_ply,
            hands,
            shows,
            plays,
            winners,
            _reserved,
        ) = _DEAL_STRUCT.unpack(payload)
        decoded_plays = unpack_plays(plays)
        decoded_shows = unpack_shows(shows)
        if len(decoded_shows) != show_count:
            raise CorpusFormatError("stored show count disagrees with the show slots")
        return cls(
            match_row=match_row,
            deal_number=deal_number,
            dealer=dealer,
            forehand=forehand,
            contract=Contract.RAMI if contract_bit else Contract.NOLO,
            declarer=None if declarer == NONE_U8 else declarer,
            first_leader=first_leader,
            hands=unpack_hands(hands),
            shows=decoded_shows,
            plays=decoded_plays,
            trick_winners=unpack_trick_winners(winners, len(decoded_plays) // 4),
            team_tricks=(tricks0, tricks1),
            deal_points=(points0, points1),
            score_before=(before0, before1),
            score_after=(after0, after1),
            flags=flags,
            branch_ply=None if branch_ply == NONE_U16 else branch_ply,
            stratum_detail=stratum_detail,
        )

    @property
    def forced_contract(self) -> bool:
        return bool(self.flags & FLAG_FORCED_CONTRACT)

    @property
    def revalidated(self) -> bool:
        """True when this deal was also checked through the authoritative path."""

        return bool(self.flags & FLAG_REVALIDATED)


__all__ = [
    "DEAL_ROW_BYTES",
    "FLAG_EPSILON_BRANCH",
    "FLAG_FORCED_CONTRACT",
    "FLAG_FORCED_PLAY",
    "FLAG_MATCH_TERMINAL",
    "FLAG_RESET",
    "FLAG_REVALIDATED",
    "FLAG_SOFTENED",
    "FLAG_VERBAL_REQUIRED",
    "MATCH_ROW_BYTES",
    "NONE_U16",
    "NONE_U32",
    "NONE_U8",
    "RECORDS_SCHEMA_VERSION",
    "DealRecord",
    "MatchRecord",
]
