"""Subprocess harness for the native controller (native/tuppi_browser.c, tb_*).

The controller keeps process-wide globals, so every check runs in its own
interpreter; TUPPI_NATIVE_LIBRARY selects the library (the unmodified build
for bit-identity checks). Networks come from models/compact (tools/export_compact.py).

    python tests/tb_controller.py trace MODE WORLDS ROLES PEOPLE SEEDS [INFERENCE]
    python tests/tb_controller.py anchor MODE ROLES SEEDS
    python tests/tb_controller.py restore MODE ROLES PEOPLE SEEDS
    python tests/tb_controller.py refuse
    python tests/tb_controller.py liteparity MODE PEOPLE SEEDS
    python tests/tb_controller.py rawpib ROLES
    python tests/tb_controller.py compact MODES

ROLES, PEOPLE and SEEDS are comma-separated (PEOPLE may be empty: "-").
Prints one JSON document.
"""
from __future__ import annotations

import ctypes as C
import json
from pathlib import Path
import random
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tuppi_ai import native  # noqa: E402

lib = native.lib
COMPACT = ROOT / "models/compact"
I32P, F32P, F64P, U8P = C.POINTER(C.c_int32), C.POINTER(C.c_float), C.POINTER(C.c_double), C.POINTER(C.c_uint8)
lib.tb_load_model.argtypes = [C.c_int] * 6 + [F32P]
lib.tb_configure.argtypes = [C.c_int, F64P]
lib.tb_configure_bot.argtypes = [C.c_int, C.c_int]
lib.tb_configure_inference.argtypes = [C.c_int, C.c_int]
lib.tb_configure_bids.argtypes = [C.c_int]
lib.tb_set_human_seats.argtypes = [C.c_int]
lib.tb_init.argtypes = [I32P, C.c_int, C.c_int, C.c_int]
lib.tb_legal.argtypes = [C.c_int, I32P]
lib.tb_apply.argtypes = [C.c_int]
lib.tb_state.argtypes = [C.c_int]
lib.tb_choose.argtypes = [C.c_int]
lib.tb_choose_observation.argtypes = [C.POINTER(native.TcObs), I32P, C.c_int]
lib.tb_values.argtypes = [I32P, F64P]
lib.tb_context.argtypes = [C.c_int, C.c_int]
lib.tb_context.restype = C.c_uint32
lib.tb_restore_context.argtypes = [C.c_int, C.c_uint32, C.c_uint32, C.c_int]
lib.tb_restore_net_context.argtypes = [C.c_int] + [C.c_uint32] * 4
lib.tb_features.argtypes = [C.c_int, C.c_int, U8P]
lib.tb_inference.argtypes = [C.c_int, U8P, C.c_int, F32P]
lib.tb_dispose.argtypes = []
lib.tb_dispose.restype = None

PH_DONE = 2
_keep = []  # weights stay alive while the controller holds them (it copies them, but be safe)


def networks() -> dict[int, tuple[dict, np.ndarray]]:
    manifest = json.loads((COMPACT / "models.json").read_text())
    return {r["role"]: (r, np.fromfile(COMPACT / r["file"], dtype="<f4")) for r in manifest["models"]}


def load(roles) -> None:
    nets = networks()
    for role in roles:
        r, flat = nets[role]
        _keep.append(flat)
        rc = lib.tb_load_model(role, r["in_dim"], r["config"]["width"], r["config"]["blocks"],
                               r["config"]["encoder"], len(flat), flat.ctypes.data_as(F32P))
        if rc:
            raise SystemExit(f"tb_load_model({role}) = {rc}")


def equity() -> np.ndarray:
    table = np.fromfile(COMPACT / "equity.f64", dtype="<f8")
    _keep.append(table)
    return table


def configure(worlds: int) -> int:
    return lib.tb_configure(worlds, equity().ctypes.data_as(F64P))


def setup(roles, worlds: int, mode: int, people: int, inference: int = 0) -> None:
    load(roles)
    if configure(worlds):
        raise SystemExit("tb_configure failed")
    if lib.tb_configure_bot(mode, people):
        raise SystemExit("tb_configure_bot failed")
    if inference and lib.tb_configure_inference(inference, 1):
        raise SystemExit("tb_configure_inference failed")


def deal(seed: int) -> tuple[list[int], int, int, int]:
    rng = random.Random(f"heidi12-controller|{seed}")
    cards = list(range(52))
    rng.shuffle(cards)
    score = 4 * rng.randrange(13)
    return cards, seed % 4, *((score, 0) if seed % 2 else (0, score))


def init(seed: int) -> None:
    cards, dealer, s0, s1 = deal(seed)
    if lib.tb_init((C.c_int32 * 52)(*cards), dealer, s0, s1):
        raise SystemExit("tb_init failed")


def context(seat: int) -> list[int]:
    return [int(lib.tb_context(seat, f)) for f in range(7)]


def values() -> list[list]:
    ids, vals = (C.c_int32 * 210)(), (C.c_double * 210)()
    n = lib.tb_values(ids, vals)
    return [[int(ids[i]), float(vals[i]).hex()] for i in range(n)]


def legal(seat: int) -> list[int]:
    out = (C.c_int32 * 210)()
    return list(out[:lib.tb_legal(seat, out)])


def network_argmax(role: int, seat: int) -> int:
    """The role's first maximum over the legal ids (the controller's tie rule)."""
    feat = np.zeros(2048, dtype=np.uint8)
    dim = lib.tb_features(seat, 2, feat.ctypes.data_as(U8P))
    logits = np.zeros(156, dtype=np.float32)
    if dim != 1951 or lib.tb_inference(role, feat.ctypes.data_as(U8P), 1, logits.ctypes.data_as(F32P)):
        raise SystemExit("tb_inference failed")
    ids = [a for a in legal(seat) if a < 156]
    best = ids[0]
    for a in ids[1:]:
        if logits[a] > logits[best]:
            best = a
    return best


def play(record_values: bool = True, stop_at: int | None = None, check_role: int | None = None) -> list[dict]:
    """Decide every move of the current deal by tb_choose; stop when n_played reaches stop_at."""
    rows = []
    while lib.tb_state(0) != PH_DONE:
        if stop_at is not None and lib.tb_state(6) >= stop_at:
            break
        seat, phase = lib.tb_state(1), lib.tb_state(0)
        greedy = network_argmax(check_role, seat) if check_role is not None and phase in (0, 1) else None
        action = lib.tb_choose(seat)
        if action < 0:
            raise SystemExit(f"tb_choose = {action}")
        row = {"seat": seat, "phase": phase, "n_played": lib.tb_state(6), "action": action,
               "context": context(seat)}
        if record_values:
            row["values"] = values()
        if greedy is not None:
            row["greedy"] = greedy
        rows.append(row)
        if lib.tb_apply(action) < 0:
            raise SystemExit("tb_apply failed")
    return rows


def ints(text: str) -> list[int]:
    return [] if text == "-" else [int(x) for x in text.split(",") if x]


def cmd_trace(mode, worlds, roles, people, seeds, inference="0") -> dict:
    """Every decision of fixed deals: actions, values (hex) and all seven cursor words.
    INFERENCE 8 selects PIB8 (tb_configure_inference); 0 keeps tb_configure_bot's PIB4."""
    mask = sum(1 << s for s in ints(people))
    setup(ints(roles), int(worlds), int(mode), mask, inference=int(inference))
    out = {}
    for seed in ints(seeds):
        init(seed)
        out[seed] = play()
    lib.tb_dispose()
    return {"deals": out}


def cmd_anchor(mode, roles, seeds) -> dict:
    """Anchor-only bids (tb_configure_bids(1)): the first bid of each deal and both networks' argmax."""
    roles = ints(roles)
    setup(roles, 128, int(mode), 0, inference=8)
    if lib.tb_configure_bids(1):
        raise SystemExit("tb_configure_bids failed")
    rows = []
    for seed in ints(seeds):
        init(seed)
        seat = lib.tb_state(1)
        before = context(seat)
        action = lib.tb_choose(seat)
        rows.append({"seed": seed, "seat": seat, "action": action, "values": values(),
                     "cursor_unchanged": before == context(seat),
                     "argmax": {role: network_argmax(role, seat) for role in roles if role > 0}})
    lib.tb_dispose()
    return {"rows": rows}


def cmd_restore(mode, roles, people, seeds) -> dict:
    """Play a deal; then rebuild the controller, replay the prefix, restore every seat's cursors
    (tb_restore_context and tb_restore_net_context) and finish: the suffix must repeat."""
    mode, roles, mask = int(mode), ints(roles), sum(1 << s for s in ints(people))
    setup(roles, 128, mode, mask)
    role = 2 if mode == 3 else 1
    result = []
    for seed in ints(seeds):
        lib.tb_configure_bot(mode, mask)  # fresh cursors per deal
        init(seed)
        full = play(record_values=False, check_role=role)
        cut = next((i for i, r in enumerate(full) if r["n_played"] >= 26), len(full))
        saved = {}
        for row in full[:cut]:
            saved[row["seat"]] = row["context"]
        initial = {}
        if configure(128) or lib.tb_configure_bot(mode, mask):
            raise SystemExit("reconfigure failed")
        for seat in range(4):
            initial[seat] = context(seat)
        init(seed)
        for row in full[:cut]:
            if lib.tb_apply(row["action"]) < 0:
                raise SystemExit("prefix replay failed")
        net_restores = []
        for seat, words in saved.items():
            if lib.tb_restore_context(seat, words[0], words[1], words[2]):
                raise SystemExit("tb_restore_context failed")
            net_restores.append(lib.tb_restore_net_context(seat, *words[3:7]))
        rest = play(record_values=False)
        result.append({"seed": seed, "cut": cut, "decisions": len(full),
                       "suffix_equal": [r["action"] for r in rest] == [r["action"] for r in full[cut:]]
                       and [r["context"] for r in rest] == [r["context"] for r in full[cut:]],
                       "net_restores": net_restores,
                       "cursors_moved": any(saved[s][3:7] != initial[s][3:7] for s in saved),
                       "greedy_checked": sum(1 for r in full if "greedy" in r and r["n_played"] < 16),
                       "greedy_equal": all(r["action"] == r["greedy"] for r in full
                                           if "greedy" in r and r["n_played"] < 16),
                       "actions": [r["action"] for r in full]})
    lib.tb_dispose()
    return {"deals": result}


def cmd_refuse() -> dict:
    """Return codes when a mode's network role is missing, and the per-mode API gates."""
    nets = networks()
    out = {"load_role_3": lib.tb_load_model(3, 1951, 256, 2, 2, 804508, nets[0][1].ctypes.data_as(F32P))}
    load([0])
    out["configure_0"] = configure(128)
    lib.tb_dispose()
    feat, logits = np.zeros(2048, dtype=np.uint8), np.zeros(156, dtype=np.float32)
    for roles in ([0, 1], [0, 2], [0, 1, 2]):
        key = "".join(map(str, roles))
        load(roles)
        out[f"configure_{key}"] = configure(128)
        init(0)
        # tb_configure leaves mode 0, which needs role 1.
        out[f"choose_mode0_{key}"] = lib.tb_choose(lib.tb_state(1))
        out[f"bot_{key}"] = {m: lib.tb_configure_bot(m, 0) for m in range(-1, 6)}
        gates = {}
        for m in range(5):
            if lib.tb_configure_bot(m, 0) == 0:
                gates[m] = {"inference": lib.tb_configure_inference(8, 1), "bids": lib.tb_configure_bids(1),
                            "net_context": lib.tb_restore_net_context(0, 1, 2, 3, 4)}
        out[f"gates_{key}"] = gates
        lib.tb_features(0, 2, feat.ctypes.data_as(U8P))
        out[f"inference_{key}"] = {role: lib.tb_inference(role, feat.ctypes.data_as(U8P), 1,
                                                          logits.ctypes.data_as(F32P)) for role in range(-1, 4)}
        lib.tb_dispose()
    return out


def cmd_liteparity(mode, people, seeds) -> dict:
    """Native mode 1/3 (tb_choose_observation) against Python LiteAgent(C1H) on the same engine states."""
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import card_from_index
    from tuppi_ai.bridge import action_id, obs_from_player_observation
    from tuppi_ai.lite import C1H, MODEL, MODEL_V4, LiteAgent

    mode, seats = int(mode), ints(people)
    setup([0, 1, 2], 128, mode, sum(1 << s for s in seats))
    agents = {s: LiteAgent(s, options=C1H, model=MODEL_V4 if mode == 3 else MODEL) for s in range(4)}
    compared = differ = 0
    for seed in ints(seeds):
        cards, dealer, s0, s1 = deal(seed)
        hands = tuple(tuple(card_from_index(c) for c in cards[s * 13:(s + 1) * 13]) for s in range(4))
        state = begin_explicit_deal(create_match(initial_score=MatchScore(s0, s1), initial_dealer=dealer,
                                                 match_ref="heidi12-lite", ruleset_id=RulesetId.PROJECT_TARGET_V3),
                                    ExplicitDeal(dealer=dealer, hands=hands))
        while state.phase in ACTIVE_PHASES:
            seat = state.current_actor
            observation = match_observation_for(state, seat)
            agents[seat].set_human_seats(seats)
            action = agents[seat].choose_action(observation)
            ids = [action_id(a) for a in observation.legal_actions]
            native_id = lib.tb_choose_observation(C.byref(obs_from_player_observation(observation)),
                                                  (C.c_int32 * len(ids))(*ids), len(ids))
            compared += 1
            differ += native_id != action_id(action)
            state = apply_match_action(state, action)
    cursors_python = [[a.rng.value, a.gate_rng.value, a.belief_rng.value] for a in agents.values()]
    cursors_native = [[(w[1] << 32) | w[0], (w[4] << 32) | w[3], (w[6] << 32) | w[5]]
                      for w in (context(s) for s in range(4))]
    lib.tb_dispose()
    return {"compared": compared, "differ": differ, "cursors_equal": cursors_python == cursors_native,
            "torch": "torch" in sys.modules}


#: (seed, moves before the decision, seats played by people): fixed engine roots for the hosted path.
ROOTS = ((0, 0, ()), (1, 7, (0, 2)), (2, 22, ()), (3, 37, (1,)), (4, 46, ()), (5, 1, (3,)))


def engine_roots():
    """(observation, human seats) at each root; prefixes take the first legal action (library-free)."""
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import card_from_index
    roots = []
    for seed, moves, people in ROOTS:
        cards, dealer, s0, s1 = deal(seed)
        hands = tuple(tuple(card_from_index(c) for c in cards[s * 13:(s + 1) * 13]) for s in range(4))
        state = begin_explicit_deal(create_match(initial_score=MatchScore(s0, s1), initial_dealer=dealer,
                                                 match_ref="heidi12-roots", ruleset_id=RulesetId.PROJECT_TARGET_V3),
                                    ExplicitDeal(dealer=dealer, hands=hands))
        for _ in range(moves):
            seat = state.current_actor
            state = apply_match_action(state, match_observation_for(state, seat).legal_actions[0])
        roots.append((match_observation_for(state, state.current_actor), people))
    return roots


def initial_context(seat: int) -> list[int]:
    rng = (2 * seat) * 2654435761 + 1
    return [rng & 0xffffffff, rng >> 32, 0]


def cmd_rawpib(roles) -> dict:
    """Mode 2, W1024, PIB8 through tb_choose_observation on the fixed roots (any library build)."""
    from tuppi_ai.bridge import action_id, obs_from_player_observation
    setup(ints(roles), 1024, 2, 0, inference=8)
    rows = []
    for observation, people in engine_roots():
        seat = observation.observing_seat
        ids = [action_id(a) for a in observation.legal_actions]
        if lib.tb_set_human_seats(sum(1 << s for s in people)) or lib.tb_restore_context(seat, *initial_context(seat)):
            raise SystemExit("restore failed")
        action = lib.tb_choose_observation(C.byref(obs_from_player_observation(observation)),
                                           (C.c_int32 * len(ids))(*ids), len(ids))
        rows.append({"action": action, "context": context(seat)[:3], "values": values()})
    lib.tb_dispose()
    return {"rows": rows}


def cmd_compact(modes) -> dict:
    """CompactController on the fixed roots, switching modes in the given order (e.g. 2,4,2)."""
    from tuppi_ai.bridge import action_id
    from tuppi_ai.compact import CompactController
    modes = ints(modes)
    controller = CompactController(mode=modes[0])
    roots = engine_roots()
    runs = []
    try:
        for mode in modes:
            rows = []
            for observation, people in roots:
                seat = observation.observing_seat
                action, cursor, vals = controller.choose(observation, initial_context(seat), people, mode=mode)
                rows.append({"action": action_id(action), "context": cursor,
                             "values": [[k, float(v).hex()] for k, v in vals.items()]})
            runs.append({"mode": mode, "controller_mode": controller.mode, "rows": rows})
    finally:
        controller.close()
    return {"runs": runs, "torch": "torch" in sys.modules}


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    print(json.dumps(globals()[f"cmd_{command}"](*args)))
