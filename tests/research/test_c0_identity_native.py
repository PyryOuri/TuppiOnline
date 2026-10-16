"""A01 identities, A02 native ownership, A04 ABI and malformed-input rejection."""

from __future__ import annotations

import ctypes as C
import json
import shutil

import numpy as np
import pytest

from tuppi_ai.research import identity as ident
from tuppi_ai.research.native_api import (INSTALLED_DYLIB, RESEARCH_LIB, SOURCE_LIB, NativeCallError,
                                          NativeOwnershipError, ResearchLibrary, bind_native)

from tuppi_ai.research.testing import tobs_of


def test_A01_engine_resolves_to_v3_checkout_and_no_research_engine_loaded():
    imp = ident.import_identity()
    assert imp["engine_resolves_to_v3_checkout"], imp
    assert imp["research_modules_loaded"] == []


def test_A01_loaded_library_model_equity_and_encoder_identities(nat):
    lib = ident.native_identity()
    assert lib["path"] == str(RESEARCH_LIB) and lib["mapped_tuppi_images"] == [str(RESEARCH_LIB)]
    assert lib["struct_sizes"] == lib["ctypes_sizes"]
    model = ident.model_identity()
    assert model["sha256"] == ident.ASSETS["rollout_model"][1]
    assert model["config"] == {"width": 256, "blocks": 2, "encoder": 2} and model["input_width"] == 1951
    assert ident.equity_identity()["sha256"] == ident.ASSETS["equity"][1]
    for key, (path, audit) in ident.ASSETS.items():
        assert ident.accepted_asset(key, ident.sha256_file(path), audit), key


def test_A01_baseline_manifest_is_immutable_and_still_describes_the_workspace():
    path = ident.OUTPUT_DIR / "research" / "baseline_manifest.json"
    stored = json.loads(path.read_text())
    for alias, c in stored["checkouts"].items():
        now = ident.git_identity(alias)
        assert c["head"] == ident.AUDIT_HEADS[alias], alias  # the stored manifest is the audit record
        assert ident.head_descends_from_audit(alias, now["head"]), alias
    with pytest.raises(FileExistsError):
        ident.write_once(path, {"different": True})
    drift = json.loads((ident.OUTPUT_DIR / "research" / "source_drift.json").read_text())
    assert drift["changed_or_missing"] == [] and len(drift["files"]) == 62


def test_A01_best_factory_seed_map_is_seed_plus_two_seats(nat):
    from tuppi_ai.research.lifecycle import AgentSpec

    manifest = ident.entrypoint_identity(seed=5)
    for seat in range(4):
        agent = AgentSpec.of("best", seat, worlds=4, seed=5).construct()
        expected = manifest["seat_seed_map"][str(seat)]
        assert agent.searcher.rng.value == expected["scalar_rng_initial"]
        fresh = np.random.default_rng(expected["numpy_default_rng_seed"])
        assert agent.searcher.np_rng.bit_generator.state == fresh.bit_generator.state
        assert agent.searcher.worlds == 4 and agent.searcher.dd_left == 6 and agent.search_showing == 1


def test_A02_crossing_library_handles_is_rejected(research, nat, net, tmp_path, f02):
    # A second, distinct copy of the research build has its own ownership domain.
    other_path = tmp_path / "libtuppi_research_copy.dylib"
    shutil.copy(RESEARCH_LIB, other_path)
    other = ResearchLibrary(other_path)
    assert other.lib_id != research.lib_id and not other.owns_native_module
    own_env = other.new_env(64, 0, encoder=2)
    own_mlp = other.new_mlp(net)
    obs = tobs_of(f02[0])
    ids = list(f02[0].ordered_action_ids)
    # tuppi_ai.native handles belong to the bound library, not to the copy ...
    with pytest.raises(NativeOwnershipError):
        other.trace_search(nat.Env(64, 0, encoder=2), nat.Mlp(net), obs, ids, 2, 6, C.c_uint64(1))
    # ... and the copy's handles are refused by the bound library.
    with pytest.raises(NativeOwnershipError):
        research.trace_search(own_env, own_mlp, obs, ids, 2, 6, C.c_uint64(1))
    with pytest.raises(NativeOwnershipError):
        research.env_config(own_env)
    with pytest.raises(NativeOwnershipError):
        research.trace_search(nat.Env(64, 0, encoder=2), own_mlp, obs, ids, 2, 6, C.c_uint64(1))
    # the installed and source builds are not research builds at all
    for path in (INSTALLED_DYLIB, SOURCE_LIB):
        with pytest.raises(NativeOwnershipError):
            ResearchLibrary(path)
    # and tuppi_ai.native cannot be rebound in a process that already bound it
    with pytest.raises(NativeOwnershipError):
        bind_native(INSTALLED_DYLIB)


def test_A04_abi_layout_and_field_order_agree(research):
    abi = research.check_abi()
    assert abi["agrees"] and abi["field_order_matches"] and abi["byteorder"] == "little"
    assert abi["native"][2] == 184 and abi["native"][4 + 29] == 152


def test_A04_malformed_dimensions_and_overflow_are_rejected_natively(research, nat, mlp, search_env, f02):
    obs = tobs_of(f02[0])
    acts = np.array(f02[0].ordered_action_ids, dtype=np.int32)
    k = len(acts)
    values = np.zeros(k)
    cells = np.zeros(16 * k)
    status = np.zeros(16 * k, dtype=np.uint8)
    worlds = (nat.TcDeal * 16)()
    L, h, m = research.lib, search_env._h, mlp._h

    def trace(w, kk, dd, cap, wcap=16, options=0):
        return L.research_trace_search(h, m, C.byref(obs), acts.ctypes.data, kk, w, dd, options,
                                       C.byref(C.c_uint64(1)), values.ctypes.data, cells.ctypes.data,
                                       status.ctypes.data, cap, worlds, wcap, None)

    assert trace(0, k, 6, 16 * k) == -4           # no worlds
    assert trace(8, 0, 6, 16 * k) == -4           # no actions
    assert trace(8, k, 14, 16 * k) == -4          # tail beyond 13 tricks
    assert trace(1 << 30, 211, 6, 16 * k) == -4   # above the w and k caps (which already bound w * k)
    assert trace(16, k, 6, 16 * k - 1) == -4      # cell buffer too small
    assert trace(16, k, 6, 16 * k, wcap=15) == -4  # world buffer too small
    assert trace(16, k, 6, 16 * k, options=2) == -4  # an unknown research switch
    small = nat.Env(8, 0, encoder=2)
    assert L.research_trace_search(small._h, m, C.byref(obs), acts.ctypes.data, k, 16, 6, 0, C.byref(C.c_uint64(1)),
                                   values.ctypes.data, cells.ctypes.data, status.ctypes.data, 16 * k, worlds, 16,
                                   None) == -2
    assert L.research_trace_search(h, None, C.byref(obs), acts.ctypes.data, k, 16, 6, 0, C.byref(C.c_uint64(1)),
                                   values.ctypes.data, None, None, 0, None, 0, None) == -7
    with pytest.raises(NativeCallError):
        research.trace_search(small, mlp, obs, list(acts), 16, 6, C.c_uint64(1))


def test_A04_world_observation_mismatch_is_rejected(research, nat, mlp, search_env, f02):
    obs = tobs_of(f02[0])
    ids = list(f02[0].ordered_action_ids)
    worlds = research.sample_worlds(search_env, obs, 2, C.c_uint64(7))
    assert [research.world_consistent(obs, w) for w in worlds] == ["ok", "ok"]
    bad = nat.TcDeal()
    C.pointer(bad)[0] = worlds[0]
    mine, other = obs.seat, (obs.seat + 1) % 4
    a = next(c for c in range(52) if bad.hand[mine] >> c & 1)
    b = next(c for c in range(52) if bad.hand[other] >> c & 1)
    bad.hand[mine] = (bad.hand[mine] & ~(1 << a)) | (1 << b)    # the root's own hand changed
    bad.hand[other] = (bad.hand[other] & ~(1 << b)) | (1 << a)
    assert research.world_consistent(obs, bad) == "projection"
    dup = nat.TcDeal()
    C.pointer(dup)[0] = worlds[0]
    x = next(c for c in range(52) if dup.hand[(mine + 2) % 4] >> c & 1)
    dup.hand[(mine + 3) % 4] |= 1 << x                            # a card held twice
    assert research.world_consistent(obs, dup) == "partition"
    with pytest.raises(NativeCallError) as err:
        research.evaluate_worlds(search_env, mlp, obs, [worlds[0], bad], ids, 6, C.c_uint64(0))
    assert err.value.code == -5 and "world 1" in str(err.value)


def test_A04_native_record_codecs_reject_out_of_range_values(f02):
    from tuppi_ai.research.observation import ObservationCodecError, tcobs_from_data, tcobs_to_data

    data = tcobs_to_data(tobs_of(f02[0]))
    assert tcobs_to_data(tcobs_from_data(data)) == data
    for field, value in (("seat", 4), ("phase", 7), ("n_played", 53), ("hand", 1 << 52), ("ruleset", 0)):
        with pytest.raises(ObservationCodecError):
            tcobs_from_data({**data, field: value})
    with pytest.raises(ObservationCodecError):
        tcobs_from_data({**data, "play_card": data["play_card"][:-1]})
    with pytest.raises(ObservationCodecError):
        tcobs_from_data({**data, "extra": 1})


def test_A12_protect_check_detects_each_kind_of_change():
    import copy

    before = json.loads((ident.OUTPUT_DIR / "research" / "protected_snapshot_before.json").read_text())
    assert ident.compare_protected(before, copy.deepcopy(before)) == []
    mutations = {
        "asset": lambda s: s["assets"].__setitem__("installed_dylib", "0" * 64),
        "tracked AI file": lambda s: s["ai_tracked"].__setitem__("tuppi_ai/search.py", "0" * 64),
        "other author's dirty file": lambda s: s["checkouts"]["RESEARCH"]["dirty"][0].__setitem__("sha256", "0" * 64),
        "new untracked file": lambda s: s["checkouts"]["ENGINE"]["dirty"].append({"status": "??", "path": "x.py"}),
        "HEAD": lambda s: s["checkouts"]["CLIENT"].__setitem__("head", "0" * 40),
        "run bank metadata": lambda s: s["stat_only"][next(iter(s["stat_only"]))].__setitem__("new.bin", [1, 1]),
        "input package": lambda s: s["input_packages"]["plan"].__setitem__("IMPLEMENTATION_SPEC.md", "0" * 64),
    }
    for name, mutate in mutations.items():
        after = copy.deepcopy(before)
        mutate(after)
        assert ident.compare_protected(before, after), f"{name} change not detected"


def test_A04_malformed_observations_are_rejected_before_any_native_use(research, nat, mlp, search_env, f02):
    """Built as raw ctypes structures, bypassing the Python codec, so the native checks alone must catch them."""
    good = tobs_of(f02[0])
    ids = list(f02[0].ordered_action_ids)
    worlds = research.sample_worlds(search_env, good, 2, C.c_uint64(3))
    bad_cases = {
        "seat": lambda o: setattr(o, "seat", 7),
        "n_played": lambda o: setattr(o, "n_played", 200),
        "play_seat": lambda o: o.play_seat.__setitem__(0, 9),
        "play_card": lambda o: o.play_card.__setitem__(0, 60),
        "duplicate_play": lambda o: o.play_card.__setitem__(1, o.play_card[0]),
        "hand_overlaps_played": lambda o: setattr(o, "hand", o.hand | (1 << o.play_card[0])),
        "hand_bits": lambda o: setattr(o, "hand", o.hand | (1 << 60)),
        "phase_done": lambda o: setattr(o, "phase", 2),
        "trick_size": lambda o: setattr(o, "trick_size", 5),
        "n_shows": lambda o: setattr(o, "n_shows", 5),
    }
    for name, mutate in bad_cases.items():
        o = nat.TcObs()
        C.pointer(o)[0] = good
        mutate(o)
        assert not research.obs_valid(o), name
        with pytest.raises(NativeCallError) as e1:
            research.sample_worlds(search_env, o, 2, C.c_uint64(1))
        with pytest.raises(NativeCallError) as e2:
            research.trace_search(search_env, mlp, o, ids, 2, 6, C.c_uint64(1))
        with pytest.raises(NativeCallError) as e3:
            research.evaluate_worlds(search_env, mlp, o, worlds, ids, 6)
        assert e1.value.code == e2.value.code == e3.value.code == -8, name
        assert research.world_consistent(o, worlds[0]) == "bad_observation", name
    assert research.obs_valid(good)


def test_A04_worlds_with_wrong_trick_totals_actor_or_hidden_bids_are_rejected(research, nat, search_env, f02):
    obs = tobs_of(f02[0])
    w = research.sample_worlds(search_env, obs, 1, C.c_uint64(9))[0]
    bad = nat.TcDeal()
    C.pointer(bad)[0] = w
    bad.team_tricks[0] += 1
    bad.team_tricks[1] -= 1
    assert research.world_consistent(obs, bad) == "trick_totals"
    # locked-bid showing: the hidden earlier bids must be legal NOLO bids from each bidder's hand
    case, _t = __import__("tuppi_ai.research.testing", fromlist=["x"]).fixture_case("F01", 0)
    focal = tobs_of(case)
    lw = research.sample_worlds(search_env, focal, 1, C.c_uint64(10))[0]
    assert research.world_consistent(focal, lw) == "ok"
    for mutate in (lambda d: d.show_contract.__setitem__(0, 1),                  # a RAMI would have ended showing
                   lambda d: d.show_seat.__setitem__(0, (d.show_seat[0] + 1) % 4),  # out of bidding order
                   lambda d: d.show_card.__setitem__(0, next(c for c in range(52)  # a card the bidder lacks
                                                             if not d.hand[d.show_seat[0]] >> c & 1))):
        x = nat.TcDeal()
        C.pointer(x)[0] = lw
        mutate(x)
        assert research.world_consistent(focal, x) == "bids"
