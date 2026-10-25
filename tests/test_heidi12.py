"""Heidi 1.2 / Nelli 1.1: the third network role (release contract of 2026-10-23).

Native controller checks run tests/tb_controller.py in fresh interpreters (the
controller's globals are per process). The bit-identity checks compare modes
0, 1 and 2 with a library built from the Heidi 1.1 controller source (b30763c).
"""
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests/tb_controller.py"
BEFORE_COMMIT = "b30763c"  # the Heidi 1.1 AI source
LIBRARY = Path(os.environ.get("TUPPI_NATIVE_LIBRARY", ROOT / "native" /
                              ("libtuppi.dylib" if sys.platform == "darwin" else "libtuppi.so")))


def harness(*args, library: Path = LIBRARY) -> dict:
    env = {**os.environ, "TUPPI_NATIVE_LIBRARY": str(library)}
    run = subprocess.run([sys.executable, str(HARNESS), *map(str, args)], capture_output=True, text=True,
                         cwd=ROOT, env=env)
    assert run.returncode == 0, run.stderr[-2000:]
    return json.loads(run.stdout)


@pytest.fixture(scope="module")
def before_library(tmp_path_factory) -> Path:
    """The native library with native/tuppi_browser.c as of BEFORE_COMMIT (the other sources as now)."""
    if os.environ.get("TUPPI_BEFORE_LIBRARY"):
        return Path(os.environ["TUPPI_BEFORE_LIBRARY"])
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{BEFORE_COMMIT}:native/tuppi_browser.c"],
                            capture_output=True)
    if source.returncode:
        pytest.skip(f"{BEFORE_COMMIT} is not in this checkout")
    directory = tmp_path_factory.mktemp("before") / "native"
    shutil.copytree(ROOT / "native", directory,
                    ignore=shutil.ignore_patterns("*.dylib", "*.so", "*.tmp"))
    (directory / "tuppi_browser.c").write_bytes(source.stdout)
    build = subprocess.run(["sh", str(directory / "build.sh")], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr[-2000:]
    return directory / ("libtuppi.dylib" if sys.platform == "darwin" else "libtuppi.so")


# --- hosted lite (tuppi_ai/lite.py) --------------------------------------------------------------


def test_v4_lite_export_equals_the_checkpoint_bitwise():
    from tuppi_ai import model, native
    from tuppi_ai.lite import MODEL_V4, load_mlp
    net = model.load(ROOT / "models/vrpo4_final.pt", "cpu")
    a, b = native.Mlp(net), load_mlp(MODEL_V4)
    assert (b.width, b.encoder, net.config) == (768, 2, {"width": 768, "blocks": 4, "encoder": 2})
    feat = (np.random.default_rng(2).random((64, native.feature_dim(2))) < 0.08).astype(np.uint8)
    assert np.array_equal(a.forward(feat).view(np.uint32), b.forward(feat).view(np.uint32))


def test_shared_mlp_caches_one_network_per_file():
    from tuppi_ai.lite import MODEL, MODEL_V4, LiteAgent, shared_mlp
    v3, v4 = shared_mlp(), shared_mlp(MODEL_V4)
    assert v3 is shared_mlp(MODEL) and v4 is shared_mlp(str(MODEL_V4)) and v3 is not v4
    assert (v3.width, v4.width) == (512, 768)
    assert LiteAgent(1).mlp is v3 and LiteAgent(1, model=MODEL_V4).mlp is v4
    assert LiteAgent(1, model=MODEL).mlp is v3
    with pytest.raises(ValueError):
        LiteAgent(1, mlp=v3, model=MODEL_V4)


def test_v4_lite_greedy_equals_torch_argmax_on_2000_rollout_observations():
    """LiteAgent(model=MODEL_V4).greedy_action against the Torch model's masked argmax on observations
    drawn from native self-play rollouts (20% random moves). Native and Torch logits agree to float
    rounding, not bitwise; a different action is accepted only at a Torch gap below 1e-4."""
    import torch
    from tuppi_ai import model, native
    from tuppi_ai.lite import MODEL_V4, LiteAgent, shared_equity
    torch.set_num_threads(1)
    net = model.load(ROOT / "models/vrpo4_final.pt", "cpu")
    agent = LiteAgent(0, model=MODEL_V4)
    env = native.Env(256, 20261023, equity=shared_equity(), encoder=2)
    states, n = native.selfplay_states(env, agent.mlp, 256, 3, C.c_uint64(20261023), 0.25, 0.2, 20000)
    assert 2000 <= n < 20000  # every recorded state is kept, so the set does not depend on threads
    raw = np.frombuffer(states, dtype=np.uint8).reshape(-1, C.sizeof(native.TcDeal))[:n]
    picked = sorted(range(n), key=lambda i: raw[i].tobytes())[:2000]
    observations = [native.observe(states[i], states[i].cur) for i in picked]
    feat = np.stack([native.encode(o, encoder=2) for o in observations])
    mask = np.zeros((len(observations), 156), dtype=np.uint8)
    lite = []
    for row, obs in enumerate(observations):
        ids = native.legal_obs(obs)
        assert len(ids) > 1 and max(ids) < 156 and obs.phase in (native.PH_SHOW, native.PH_PLAY)
        mask[row, ids] = 1
        lite.append(agent.greedy_action(obs, ids))
    with torch.no_grad():
        q = net(torch.from_numpy(feat))
        expected = model.masked_argmax(q, torch.from_numpy(mask)).numpy()
    differ = [i for i in range(len(lite)) if lite[i] != expected[i]]
    assert all(float(q[i, expected[i]] - q[i, lite[i]]) < 1e-4 for i in differ), differ
    assert len(differ) <= 2, differ
    assert {o.phase for o in observations} == {native.PH_SHOW, native.PH_PLAY}


def test_native_lite_modes_equal_python_lite_agents():
    """Mode 3 (Nelli 1.1) is LiteAgent(C1H, MODEL_V4) and mode 1 (Nelli 1.0) LiteAgent(C1H) on the
    same engine states: every action and every cursor, with and without people marked; no PyTorch."""
    for mode, people, seeds in ((3, "0", "0,1,2,3"), (3, "-", "4,5"), (1, "0,2", "0,1,2,3")):
        result = harness("liteparity", mode, people, seeds)
        assert result["compared"] > 100 and result["differ"] == 0 and result["cursors_equal"], result
        assert not result["torch"]


# --- native controller (native/tuppi_browser.c) --------------------------------------------------


def test_controller_refuses_a_mode_whose_network_is_missing():
    r = harness("refuse")
    assert r["load_role_3"] == -1 and r["configure_0"] == -1
    assert r["configure_01"] == r["configure_02"] == r["configure_012"] == 0
    # Mode 4 (Heidi 1.2) reads all three roles: role 2 as the anchor, role 1 as the likelihood model.
    assert r["bot_01"] == {"-1": -1, "0": 0, "1": 0, "2": 0, "3": -1, "4": -1, "5": -1}
    assert r["bot_02"] == {"-1": -1, "0": -1, "1": -1, "2": -1, "3": 0, "4": -1, "5": -1}
    assert r["bot_012"] == {"-1": -1, "0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5": -1}
    assert r["choose_mode0_02"] == -1 and r["choose_mode0_01"] >= 0 and r["choose_mode0_012"] >= 0
    gates = {"0": {"inference": -1, "bids": -1, "net_context": -1},
             "1": {"inference": -1, "bids": -1, "net_context": 0},
             "2": {"inference": 0, "bids": 0, "net_context": -1},
             "3": {"inference": -1, "bids": -1, "net_context": 0},
             "4": {"inference": 0, "bids": 0, "net_context": -1}}
    assert r["gates_012"] == gates
    assert r["gates_01"] == {m: gates[m] for m in "012"} and r["gates_02"] == {"3": gates["3"]}
    assert r["inference_01"] == {"-1": -1, "0": 0, "1": 0, "2": -1, "3": -1}
    assert r["inference_02"] == {"-1": -1, "0": 0, "1": -1, "2": 0, "3": -1}
    assert r["inference_012"] == {"-1": -1, "0": 0, "1": 0, "2": 0, "3": -1}


def test_mode4_anchor_is_the_role2_network_and_mode2_the_role1_network():
    """Anchor-only bids (tb_configure_bids(1)) return the anchor itself, with no search or RNG draw:
    role 2's argmax in mode 4 (Heidi 1.2's anchor), role 1's in mode 2."""
    seeds = ",".join(map(str, range(16)))
    for mode, role in ((4, "2"), (2, "1")):
        rows = harness("anchor", mode, "0,1,2", seeds)["rows"]
        assert all(r["action"] == r["argmax"][role] for r in rows), (mode, rows)
        assert all(r["cursor_unchanged"] and r["values"] == [] for r in rows)
        assert sum(r["argmax"]["1"] != r["argmax"]["2"] for r in rows) >= 1  # the roots tell the networks apart


def test_mode3_plays_role2_and_restores_cursors_like_mode1():
    """Nelli 1.1 plays whole deals on roles {0, 2}: its greedy moves (bids and the first four tricks)
    are role 2's argmax, and a rebuilt controller with the prefix replayed and every cursor restored
    finishes each deal exactly. Mode 1 on roles {0, 1} passes the same check with role 1."""
    actions = {}
    for mode, roles in ((3, "0,2"), (1, "0,1")):
        deals = harness("restore", mode, roles, "0", "0,1,2,3")["deals"]
        for d in deals:
            assert d["suffix_equal"] and d["net_restores"] == [0] * len(d["net_restores"]), (mode, d)
            assert d["cursors_moved"] and d["greedy_checked"] >= 16 and d["greedy_equal"], (mode, d)
        actions[mode] = [d["actions"] for d in deals]
    assert actions[1] != actions[3]


def keep_rule(values: list, anchor: int, margin: float) -> int:
    """tb_choose's non-adaptive keep rule from its recorded values: the search's first maximum, or
    the anchor when its value is within the margin of it."""
    ids, v = [i for i, _ in values], [float.fromhex(h) for _, h in values]
    best = max(range(len(v)), key=lambda i: (v[i], -i))
    return anchor if v[ids.index(anchor)] >= v[best] - margin else ids[best]


def check_anchor_only(rows: list, adaptive: bool) -> dict:
    """Mode 4 against mode 2 from the same position and cursor (tests/tb_controller.py keeprule):
    the search is the same (role 0 rollouts, role 1 likelihood), so values and cursors are always
    equal; where roles 1 and 2 have the same argmax the decisions are equal bit for bit, and where
    they differ only the keep rule can differ."""
    counts = {"agree": 0, "disagree": 0, "kept_both": 0}
    for row in rows:
        two, four = row["2"], row["4"]
        assert two["values"] == four["values"] and two["context"] == four["context"], row["root"]
        argmax = row["argmax"]
        if not argmax or not two["values"] or argmax["1"] == argmax["2"]:
            assert two == four, row["root"]
            counts["agree"] += bool(argmax and two["values"])
            continue
        counts["disagree"] += 1
        if adaptive:  # the adaptive bid search's leader is not recomputable from its means
            searched = {m["action"] for m, role in ((two, "1"), (four, "2")) if m["action"] != argmax[role]}
            assert len(searched) <= 1, row
        else:
            margin = 0.03 if row["phase"] == 0 else 0.003
            assert two["action"] == keep_rule(two["values"], argmax["1"], margin), row
            assert four["action"] == keep_rule(four["values"], argmax["2"], margin), row
        counts["kept_both"] += two["action"] == argmax["1"] and four["action"] == argmax["2"]
    return counts


def test_mode4_is_mode2_with_role2_as_the_anchor_only():
    """Heidi 1.2 (anchor only): bids, play and sooli phases at W128 PIB8 with a person marked, and the
    adaptive bid search at W256. Mode 4 equals mode 2 bit for bit (action, values and all seven
    cursor words) where roles 1 and 2 agree; elsewhere values and cursors are still equal and each
    mode's action is its own anchor's keep rule. A role-2 likelihood model would change the values."""
    roots = ",".join(f"{s}:{m}" for s in range(8) for m in (0, 1, 2, 3, 5, 9, 17, 26, 35, 44))
    counts = check_anchor_only(harness("keeprule", 128, "1", roots)["rows"], adaptive=False)
    # Coverage only: both branches must be exercised. How often the two anchors agree depends on
    # the network (stand-in 49/20, final VRPO4 34/35), so the floors do not assume a split.
    assert counts["agree"] >= 10 and counts["disagree"] >= 10 and counts["kept_both"] >= 5, counts
    bids = harness("keeprule", 256, "-", "0:3,1:0,2:1,3:0,4:2,5:3,6:1,7:0")["rows"]
    assert all(row["phase"] == 0 and row["argmax"] for row in bids)
    counts = check_anchor_only(bids, adaptive=True)
    assert counts["agree"] >= 1 and counts["disagree"] >= 1, counts


def test_modes_0_1_2_are_bit_identical_to_the_heidi11_controller(before_library):
    """Whole deals by tb_choose: actions, values (exact) and all seven cursor words, with roles {0, 1}
    on the old build and with roles {0, 1} and {0, 1, 2} on the new one. Covers searched bids and play,
    sooli phases, PIB4/PIB8, people marked, and the adaptive bid search (W256)."""
    cases = (("0", "128", "-", "0,1", "0"), ("1", "128", "0", "0,1,2,3", "0"), ("1", "128", "-", "6", "0"),
             ("2", "128", "1", "0,1", "8"), ("2", "256", "-", "3", "0"))
    for mode, worlds, people, seeds, inference in cases:
        reference = harness("trace", mode, worlds, "0,1", people, seeds, inference, library=before_library)
        assert sum(len(d) for d in reference["deals"].values()) > 0
        for roles in ("0,1", "0,1,2"):
            assert harness("trace", mode, worlds, roles, people, seeds, inference) == reference, (mode, roles)


# --- hosted compact controller (tuppi_ai/compact.py) ---------------------------------------------


def test_compact_directory_holds_the_three_networks():
    from tuppi_ai.compact import NETWORKS, model_identity
    identity = model_identity()
    records = identity["manifest"]["models"]
    assert [(r["role"], r["file"], r["config"]["width"]) for r in records] == [(n[0], n[1], n[2]) for n in NETWORKS]
    hosted = json.loads((ROOT / "models/hosted-models.json").read_text())
    assert records[2]["source_sha256"] == hosted["vrpo4_final.pt"]
    assert records[1]["source_sha256"] == hosted["vrpo3_final.pt"]


def test_compact_directory_and_v4_lite_equal_fresh_exports():
    for tool in (["tools/export_compact.py", "--check"],
                 ["tools/export_lite_model.py", "--model", "models/vrpo4_final.pt",
                  "--out", "models/vrpo4_final.lite.npz", "--check"]):
        run = subprocess.run([sys.executable, *tool], capture_output=True, text=True, cwd=ROOT)
        assert run.returncode == 0, run.stdout + run.stderr


def test_compact_controller_rejects_two_networks_and_other_modes(tmp_path):
    from tuppi_ai.compact import CompactController, model_identity
    shutil.copytree(ROOT / "models/compact", tmp_path / "compact")
    manifest = json.loads((tmp_path / "compact/models.json").read_text())
    manifest["models"] = manifest["models"][:2]
    (tmp_path / "compact/models.json").write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ValueError):
        model_identity(tmp_path / "compact")
    for mode in (0, 1, 3, 5, True):
        with pytest.raises(ValueError):
            CompactController(mode=mode)


def test_compact_mode2_equals_the_heidi11_controller_and_modes_switch_exactly(before_library):
    """W1024/PIB8 on fixed engine roots: CompactController mode 2 (three networks loaded) equals mode 2
    of the old build (roles {0, 1}); switching 2 -> 4 -> 2 per call repeats mode 2 exactly, and the
    switched mode 4 equals a controller created in mode 4. Mode 4 (anchor only) has mode 2's values and
    cursors on every root and its decision wherever roles 1 and 2 have the same argmax."""
    reference = harness("rawpib", "0,1", library=before_library)["rows"]
    switched = harness("compact", "2,4,2")
    assert not switched["torch"]
    first, four, again = (run["rows"] for run in switched["runs"])
    assert [run["controller_mode"] for run in switched["runs"]] == [2, 4, 2]
    assert first == reference and again == reference
    assert harness("compact", "4")["runs"][0]["rows"] == four
    for a, b, argmax, phase in zip(first, four, switched["argmax"], switched["phases"]):
        assert a["values"] == b["values"] and a["context"] == b["context"]
        if not argmax or not a["values"] or argmax["1"] == argmax["2"]:
            assert a == b
        else:
            if phase == 0:  # W1024 bids use the adaptive search; its leader is the shared non-anchor
                assert len({r["action"] for r, role in ((a, "1"), (b, "2")) if r["action"] != argmax[role]}) <= 1
            else:
                assert (a["action"], b["action"]) == (keep_rule(a["values"], argmax["1"], 0.003),
                                                      keep_rule(a["values"], argmax["2"], 0.003))
