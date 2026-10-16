import ctypes as C
from pathlib import Path
NUM_ACTIONS = 156
NOLO, RAMI = 0, 1
PH_SHOW, PH_PLAY, PH_DONE = 0, 1, 2
# project_target_v2 (sooli): phases and the action ids outside the network head.
PH_SOOLI_OFFER, PH_SOOLI_GIVE, PH_SOOLI_RETURN, PH_SOOLI_PLAY = 3, 4, 5, 6
SOOLI_PHASES = (PH_SOOLI_OFFER, PH_SOOLI_GIVE, PH_SOOLI_RETURN, PH_SOOLI_PLAY)
ACT_SOOLI_DECLINE, ACT_SOOLI_ACCEPT, ACT_EXCHANGE = 156, 157, 158
NUM_ACTIONS_V2 = 210
U8x4 = C.c_uint8 * 4
U8x52 = C.c_uint8 * 52


class TcDeal(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64 * 4),
        ("dealer", C.c_uint8), ("phase", C.c_uint8), ("cur", C.c_uint8),
        ("n_shows", C.c_uint8),
        ("show_seat", U8x4), ("show_card", U8x4), ("show_contract", U8x4), ("show_verbal", U8x4),
        ("contract", C.c_int8), ("declarer", C.c_int8),
        ("first_leader", C.c_uint8),
        ("n_played", C.c_uint8),
        ("play_card", U8x52), ("play_seat", U8x52),
        ("team_tricks", C.c_uint8 * 2),
        ("score", C.c_uint8 * 2),
        ("winner_team", C.c_int8), ("points", C.c_uint8), ("stolen", C.c_uint8),
        ("ruleset", C.c_uint8), ("trick_size", C.c_uint8), ("n_decisions", C.c_uint8),
        ("decision_seat", C.c_uint8 * 2), ("decision_accept", C.c_uint8 * 2),
        ("soolaaja", C.c_int8), ("given", C.c_int8), ("returned", C.c_int8),
        ("sooli_won", C.c_uint8),
    ]


class TcObs(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64),
        ("seat", C.c_uint8), ("dealer", C.c_uint8), ("phase", C.c_uint8),
        ("n_shows", C.c_uint8),
        ("show_seat", U8x4), ("show_card", U8x4), ("show_contract", U8x4), ("show_verbal", U8x4),
        ("contract", C.c_int8), ("declarer", C.c_int8),
        ("first_leader", C.c_uint8),
        ("n_played", C.c_uint8),
        ("play_card", U8x52), ("play_seat", U8x52),
        ("score", C.c_uint8 * 2),
        ("ruleset", C.c_uint8), ("trick_size", C.c_uint8), ("n_decisions", C.c_uint8),
        ("decision_seat", C.c_uint8 * 2), ("decision_accept", C.c_uint8 * 2),
        ("soolaaja", C.c_int8), ("known_given", C.c_int8), ("known_returned", C.c_int8),
    ]


lib=C.CDLL(str(Path(__file__).parent / "vendor/native/libtuppi.dylib"))
