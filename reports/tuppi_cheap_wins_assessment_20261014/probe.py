#!/usr/bin/env python3
"""Small read-only mechanism probes; no Torch, training, search games or server.

Uses the existing native core and the browser's hash-checked raw model export.
Writes only inside this assessment directory. Synthetic positions use random
legal play and are not a strength or population-performance sample.
"""
from __future__ import annotations

import ast
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import random
import resource
import statistics
import time
import types

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
AI = ROOT / "TuppiAI"
ASSETS = ROOT / "TuppiBrowser/web/assets"
U8, I8 = C.c_uint8, C.c_int8


class Deal(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64 * 4), ("dealer", U8), ("phase", U8), ("cur", U8),
        ("n_shows", U8), ("show_seat", U8 * 4), ("show_card", U8 * 4),
        ("show_contract", U8 * 4), ("show_verbal", U8 * 4), ("contract", I8),
        ("declarer", I8), ("first_leader", U8), ("n_played", U8),
        ("play_card", U8 * 52), ("play_seat", U8 * 52), ("team_tricks", U8 * 2),
        ("score", U8 * 2), ("winner_team", I8), ("points", U8), ("stolen", U8),
        ("ruleset", U8), ("trick_size", U8), ("n_decisions", U8),
        ("decision_seat", U8 * 2), ("decision_accept", U8 * 2), ("soolaaja", I8),
        ("given", I8), ("returned", I8), ("sooli_won", U8),
    ]


class Obs(C.Structure):
    _fields_ = [
        ("hand", C.c_uint64), ("seat", U8), ("dealer", U8), ("phase", U8),
        ("n_shows", U8), ("show_seat", U8 * 4), ("show_card", U8 * 4),
        ("show_contract", U8 * 4), ("show_verbal", U8 * 4), ("contract", I8),
        ("declarer", I8), ("first_leader", U8), ("n_played", U8),
        ("play_card", U8 * 52), ("play_seat", U8 * 52), ("score", U8 * 2),
        ("ruleset", U8), ("trick_size", U8), ("n_decisions", U8),
        ("decision_seat", U8 * 2), ("decision_accept", U8 * 2), ("soolaaja", I8),
        ("known_given", I8), ("known_returned", I8),
    ]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_native():
    lib = C.CDLL(str(AI / "native/libtuppi.dylib"))
    signatures = {
        "tc_struct_sizes": ([C.POINTER(C.c_int)], None),
        "tc_deal_init_v": ([C.POINTER(Deal), C.POINTER(C.c_uint64)] + [C.c_int] * 4, None),
        "tc_legal": ([C.POINTER(Deal), C.POINTER(C.c_int)], C.c_int),
        "tc_apply": ([C.POINTER(Deal), C.c_int], C.c_int),
        "tc_observe": ([C.POINTER(Deal), C.c_int, C.POINTER(Obs)], None),
        "tc_encode_v": ([C.POINTER(Obs), C.POINTER(U8), C.c_int], None),
        "tc_mlp_new": ([C.c_int] * 5 + [C.POINTER(C.c_float)], C.c_void_p),
        "tc_mlp_forward": ([C.c_void_p, C.POINTER(U8), C.c_int, C.POINTER(C.c_float)], None),
        "tc_mlp_free": ([C.c_void_p], None),
        "tc_finish_with_tricks": ([C.POINTER(Deal), C.c_int], None),
        "tc_next_score": ([C.POINTER(U8), C.c_int, C.c_int, C.POINTER(U8)], C.c_int),
        "tc_dd_team0_tricks": ([C.POINTER(Deal)], C.c_int),
    }
    for name, (args, ret) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, ret
    sizes = (C.c_int * 2)()
    lib.tc_struct_sizes(sizes)
    assert list(sizes) == [C.sizeof(Deal), C.sizeof(Obs)]
    return lib


def copy(d):
    return Deal.from_buffer_copy(bytes(d))


def legal(lib, d):
    acts = (C.c_int * 210)()
    n = lib.tc_legal(C.byref(d), acts)
    assert n > 0
    return list(acts[:n])


def corpus(lib, actor=None):
    rng = random.Random(20261014)
    states = []
    for parent in range(48):
        cards = list(range(52))
        rng.shuffle(cards)
        hands = (C.c_uint64 * 4)(*[sum(1 << c for c in cards[s * 13:(s + 1) * 13]) for s in range(4)])
        score = rng.randrange(25)
        s0, s1 = (4 * score, 0) if score <= 12 else (0, 4 * (score - 12))
        d = Deal()
        lib.tc_deal_init_v(C.byref(d), hands, parent % 4, s0, s1, 3)
        while d.phase != 2:
            acts = legal(lib, d)
            if len(acts) > 1 and d.phase in (0, 1):
                states.append((parent, copy(d)))
            if actor and d.phase in (0, 1):
                ob = Obs()
                feat = (U8 * 1951)()
                q = (C.c_float * 156)()
                lib.tc_observe(C.byref(d), d.cur, C.byref(ob))
                lib.tc_encode_v(C.byref(ob), feat, 2)
                lib.tc_mlp_forward(actor, feat, 1, q)
                a = max(acts, key=lambda x: (q[x], -x))
            elif d.phase == 0:
                # Half the parents are all-NOLO, half forehand-RAMI.
                contract = parent % 2
                eligible = [a for a in acts if (a - 52) // 52 == contract]
                a = rng.choice(eligible)
            elif d.phase == 3:
                a = 156  # decline, keeping this corpus ordinary trick play
            else:
                a = rng.choice(acts)
            assert lib.tc_apply(C.byref(d), a) == 0
    return states


PERMS = [(0, 1, 2, 3), (1, 0, 2, 3), (0, 1, 3, 2), (1, 0, 3, 2)]


def card_map(c, perm):
    return perm[c // 13] * 13 + c % 13


def action_map(a, perm):
    if a < 52:
        return card_map(a, perm)
    if a < 156:
        return 52 + 52 * ((a - 52) // 52) + card_map((a - 52) % 52, perm)
    if a < 158:
        return a
    return 158 + card_map(a - 158, perm)


def permute(d, perm):
    out = copy(d)
    for s in range(4):
        out.hand[s] = sum(1 << card_map(c, perm) for c in range(52) if d.hand[s] >> c & 1)
    for i in range(d.n_shows):
        out.show_card[i] = card_map(d.show_card[i], perm)
    for i in range(d.n_played):
        out.play_card[i] = card_map(d.play_card[i], perm)
    for name in ("given", "returned"):
        if getattr(d, name) >= 0:
            setattr(out, name, card_map(getattr(d, name), perm))
    return out


def rank_equivalent(d, a, b):
    if a == b:
        return True
    if a // 13 != b // 13:
        return False
    gone = sum(1 << d.play_card[i] for i in range(d.n_played - d.n_played % 4))
    return all((gone | d.hand[d.cur]) >> c & 1 for c in range(min(a, b) + 1, max(a, b)))


def symmetry_probe(lib, states, manifest, population):
    rng = random.Random(271828)
    bids = [x for x in states if x[1].phase == 0]
    play = [x for x in states if x[1].phase == 1]
    chosen = rng.sample(bids, min(128, len(bids))) + rng.sample(play, 128)
    meta = next(x for x in manifest["models"] if x["role"] == 1)
    raw = ASSETS / meta["file"]
    assert sha(raw) == meta["sha256"]
    assert sha(AI / "models" / meta["source_file"]) == meta["source_sha256"]
    weights = (C.c_float * meta["count"]).from_buffer_copy(raw.read_bytes())
    cfg = meta["config"]
    mlp = lib.tc_mlp_new(meta["in_dim"], cfg["width"], cfg["blocks"], meta["out_dim"], cfg["encoder"], weights)
    assert mlp
    result = {"n_positions": len(chosen), "positions": {}, "commuting_transition_checks": 0,
              "scope": population + "; suit inconsistency is not strength loss."}
    timing = []
    try:
        for phase, label in ((0, "bid"), (1, "play")):
            rows = [(p, d) for p, d in chosen if d.phase == phase]
            dim, n = meta["in_dim"], len(rows)
            feat = (U8 * (4 * n * dim))()
            for i, (_, d) in enumerate(rows):
                ids = legal(lib, d)
                for j, perm in enumerate(PERMS):
                    dp = permute(d, perm)
                    assert sorted(legal(lib, dp)) == sorted(action_map(a, perm) for a in ids)
                    # Check the actual v3 transition commutes with the relabelling.
                    a = ids[i % len(ids)]
                    left, right = copy(d), copy(dp)
                    assert lib.tc_apply(C.byref(left), a) == 0
                    assert lib.tc_apply(C.byref(right), action_map(a, perm)) == 0
                    assert bytes(permute(left, perm)) == bytes(right)
                    result["commuting_transition_checks"] += 1
                    ob = Obs()
                    lib.tc_observe(C.byref(dp), dp.cur, C.byref(ob))
                    lib.tc_encode_v(C.byref(ob), C.cast(C.byref(feat, (4 * i + j) * dim), C.POINTER(U8)), cfg["encoder"])
            q = (C.c_float * (4 * n * 156))()
            start = time.perf_counter()
            lib.tc_mlp_forward(mlp, feat, 4 * n, q)
            elapsed = time.perf_counter() - start
            timing.append(elapsed)
            mismatch, ensemble_change, all_differ, contract_mismatch = 0, 0, 0, 0
            ensemble_contract_change, nonequivalent, ensemble_nonequivalent = 0, 0, 0
            spreads = []
            for i, (_, d) in enumerate(rows):
                ids = legal(lib, d)
                logits = [[float(q[(4 * i + j) * 156 + action_map(a, perm)]) for a in ids] for j, perm in enumerate(PERMS)]
                best = [max(range(len(ids)), key=z.__getitem__) for z in logits]
                mismatch += sum(b != best[0] for b in best[1:])
                all_differ += len(set(best)) > 1
                probs = []
                for z in logits:
                    top = max(z)
                    unnorm = [math.exp(x - top) for x in z]
                    total = sum(unnorm)
                    probs.append([x / total for x in unnorm])
                mean = [sum(p[a] for p in probs) / 4 for a in range(len(ids))]
                eb = max(range(len(ids)), key=mean.__getitem__)
                ensemble_change += eb != best[0]
                if phase == 0:
                    contract_mismatch += any((ids[b] - 52) // 52 != (ids[best[0]] - 52) // 52 for b in best[1:])
                    ensemble_contract_change += (ids[eb] - 52) // 52 != (ids[best[0]] - 52) // 52
                else:
                    nonequivalent += sum(not rank_equivalent(d, ids[b], ids[best[0]]) for b in best[1:])
                    ensemble_nonequivalent += not rank_equivalent(d, ids[eb], ids[best[0]])
                spreads.append(max(max(z[a] for z in logits) - min(z[a] for z in logits) for a in range(len(ids))))
            result["positions"][label] = {
                "n": n, "transformed_comparisons": 3 * n, "different_argmax": mismatch,
                "positions_with_any_different_argmax": all_differ,
                "probability_ensemble_changes_argmax": ensemble_change,
                "positions_with_contract_disagreement": contract_mismatch,
                "probability_ensemble_changes_contract": ensemble_contract_change,
                "different_argmax_outside_rank_equivalence": nonequivalent,
                "probability_ensemble_changes_outside_rank_equivalence": ensemble_nonequivalent,
                "median_max_legal_logit_spread": statistics.median(spreads),
                "batched_four_view_forward_seconds": elapsed,
            }
            # Small per-root calls, separate from the throughput batch above.
            one, four = [], []
            small_out = (C.c_float * (4 * 156))()
            for i in range(min(n, 32)):
                ptr = C.cast(C.byref(feat, 4 * i * dim), C.POINTER(U8))
                before = time.perf_counter()
                lib.tc_mlp_forward(mlp, ptr, 1, small_out)
                one.append(time.perf_counter() - before)
                before = time.perf_counter()
                lib.tc_mlp_forward(mlp, ptr, 4, small_out)
                four.append(time.perf_counter() - before)
            result["positions"][label]["root_inference_timing"] = {
                "n": len(one), "one_view_median_ms": 1000 * statistics.median(one),
                "four_view_median_ms": 1000 * statistics.median(four),
                "scope": "Native model inference only; excludes transformations, Python controller and search."}
    finally:
        lib.tc_mlp_free(mlp)
    result["native_forward_seconds_total"] = sum(timing)
    return result


def actor_corpus(lib, manifest):
    meta = next(x for x in manifest["models"] if x["role"] == 1)
    raw = ASSETS / meta["file"]
    assert sha(raw) == meta["sha256"]
    cfg = meta["config"]
    weights = (C.c_float * meta["count"]).from_buffer_copy(raw.read_bytes())
    actor = lib.tc_mlp_new(meta["in_dim"], cfg["width"], cfg["blocks"], meta["out_dim"], cfg["encoder"], weights)
    assert actor
    try:
        return corpus(lib, actor=actor)
    finally:
        lib.tc_mlp_free(actor)


class Vector(list):
    def mean(self):
        return statistics.mean(self)

    def std(self, ddof=1):
        assert ddof == 1
        return statistics.stdev(self)

    def __sub__(self, other):
        return Vector(a - b for a, b in zip(self, other))


class Matrix:
    def __init__(self, rows):
        self.rows = rows

    def __getitem__(self, key):
        sl, col = key
        assert sl == slice(None)
        return Vector(row[col] for row in self.rows)


def adaptive_probe():
    """Execute the actual method AST with deterministic paired returns."""
    tree = ast.parse((AI / "tuppi_ai/search.py").read_text())
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "Searcher")
    method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == "adaptive_values")
    method.returns = None
    for arg in method.args.args:
        arg.annotation = None
    calls = []

    def fake_values(env, mlp, obs, actions, batch, dd_left, rng):
        call = len(calls)
        calls.append(list(actions))
        rows = []
        for r in range(batch):
            a = 0.02 if call == 0 else 0.05
            b = 0.008 if call == 0 else 0.04
            c = a + (0.2 if r % 2 else -0.2)
            rows.append([[a, b, c][i] for i in actions])
        return Matrix(rows)

    namespace = {
        "np": types.SimpleNamespace(concatenate=lambda xs: Vector(y for x in xs for y in x),
                                    array=Vector, sqrt=math.sqrt, ndarray=Vector),
        "native": types.SimpleNamespace(search_world_values=fake_values, TcObs=object),
    }
    module = ast.Module(body=[method], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), "current_adaptive_values", "exec"), namespace)
    obj = types.SimpleNamespace(env=None, mlp=None, worlds=1024, dd_left=6, rng=None)
    values, best, drawn = namespace["adaptive_values"](obj, None, [0, 1, 2], 128, 2.5, 0.005)
    anchor, keep = 1, 0.03
    chosen = anchor if values[anchor] >= values[best] - keep else best
    full = [0.04625, 0.036, 0.04625]
    full_best = max(range(3), key=full.__getitem__)
    full_choice = anchor if full[anchor] >= full[full_best] - keep else full_best
    assert chosen == 0 and full_choice == 1
    return {"drawn_worlds": drawn, "action_world_counts": [128 * sum(i in xs for xs in calls) for i in range(3)],
            "returned_means": list(values), "post_search_anchor_choice": chosen,
            "fully_priced_means": full, "fully_priced_anchor_choice": full_choice,
            "scope": "Controlled actual-method example; demonstrates objective/sample mismatch, not game-strength damage."}


def payoff(lib, d, table):
    def eq(score, dealer):
        s0, s1 = score
        if s0 >= 52:
            return 1.0
        if s1 >= 52:
            return 0.0
        row = 0 if s0 == s1 == 0 else (s0 // 4 if s0 else 12 + s1 // 4)
        return table[row][int(dealer % 2 == 0)]
    out = []
    for t in range(14):
        done = copy(d)
        lib.tc_finish_with_tricks(C.byref(done), t)
        score = (U8 * 2)()
        lib.tc_next_score(done.score, done.winner_team, done.points, score)
        out.append(C.c_float(eq(score, d.dealer + 1) - eq(d.score, d.dealer)).value)
    return out


def tail_probe(lib, states):
    table = json.loads((AI / "models/equity_incumbent.json").read_text())["table"]
    tail = [x for x in states if x[1].phase == 1 and 28 <= x[1].n_played <= 47]
    rng = random.Random(314159)
    chosen = rng.sample(tail, min(256, len(tail)))
    counts, flat = [], 0
    for _, d in chosen:
        values = payoff(lib, d, table)
        lo, hi = d.team_tricks[0], d.team_tricks[0] + 13 - d.n_played // 4
        cuts = sum(values[t] != values[t - 1] for t in range(lo + 1, hi + 1))
        counts.append(cuts)
        flat += cuts == 0
    output = {"n_positions": len(chosen), "flat_payoff_ranges": flat,
              "median_distinct_payoff_buckets": statistics.median(n + 1 for n in counts),
              "scope": "Synthetic random-legal tail states; payoff buckets are exact float reward bits, not an outcome model fit."}
    dll = OUT / "dd_probe.dylib"
    if dll.exists():
        probe = C.CDLL(str(dll))
        probe.review_reset.argtypes = []
        probe.review_counters.argtypes = [C.POINTER(C.c_long)]
        probe.review_full_tricks.argtypes, probe.review_full_tricks.restype = [C.POINTER(Deal)], C.c_int
        probe.review_bucket_tricks.argtypes, probe.review_bucket_tricks.restype = [C.POINTER(Deal), C.POINTER(C.c_float)], C.c_int
        data = []
        for parent, d in chosen:
            p = payoff(lib, d, table)
            data.append((parent, d, p, (C.c_float * 14)(*p)))
        measurements, solutions = {}, {}
        for name in ("full", "bucket"):
            probe.review_reset()
            elapsed, nodes, calls, result = 0.0, 0, 0, []
            for parent, d, p, arr in data:
                before = time.perf_counter()
                t = probe.review_full_tricks(C.byref(d)) if name == "full" else probe.review_bucket_tricks(C.byref(d), arr)
                elapsed += time.perf_counter() - before
                stats = (C.c_long * 2)()
                probe.review_counters(stats)
                nodes += stats[0]
                calls += stats[1]
                result.append((t, p[t]))
            solutions[name] = result
            measurements[name] = {"wall_seconds": elapsed, "nodes": nodes, "null_window_probes": calls}
        mismatch = sum(a[1] != b[1] for a, b in zip(solutions["full"], solutions["bucket"]))
        assert mismatch == 0
        # Independently compare copied/instrumented DD against the installed solver.
        native_mismatch = 0
        for (_, d, _, _), (t, _) in zip(data, solutions["full"]):
            native_mismatch += lib.tc_dd_team0_tricks(C.byref(d)) != t
        assert native_mismatch == 0
        output.update({"measurements": measurements, "float_reward_mismatches": mismatch,
                       "installed_solver_trick_mismatches": native_mismatch,
                       "node_reduction_fraction": 1 - measurements["bucket"]["nodes"] / measurements["full"]["nodes"],
                       "microbenchmark_speedup": measurements["full"]["wall_seconds"] / measurements["bucket"]["wall_seconds"],
                       "timing_scope": "One ordered synthetic corpus, independent empty TT per method then retained TT within method. Not full-bot latency."})
        canon_dll = OUT / "dd_probe_suits.dylib"
        if canon_dll.exists():
            canon = C.CDLL(str(canon_dll))
            canon.review_reset.argtypes = []
            canon.review_counters.argtypes = [C.POINTER(C.c_long)]
            canon.review_full_tricks.argtypes, canon.review_full_tricks.restype = [C.POINTER(Deal)], C.c_int
            canon.review_bucket_tricks.argtypes, canon.review_bucket_tricks.restype = [C.POINTER(Deal), C.POINTER(C.c_float)], C.c_int
            canon_result = {}
            for name in ("full", "bucket"):
                canon.review_reset()
                elapsed, nodes, calls, mismatches = 0.0, 0, 0, 0
                for i, (parent, d, p, arr) in enumerate(data):
                    before = time.perf_counter()
                    t = canon.review_full_tricks(C.byref(d)) if name == "full" else canon.review_bucket_tricks(C.byref(d), arr)
                    elapsed += time.perf_counter() - before
                    stats = (C.c_long * 2)()
                    canon.review_counters(stats)
                    nodes += stats[0]
                    calls += stats[1]
                    mismatches += (t != solutions["full"][i][0]) if name == "full" else (p[t] != solutions["full"][i][1])
                assert mismatches == 0
                canon_result[name] = {"wall_seconds": elapsed, "nodes": nodes,
                                      "null_window_probes": calls, "mismatches": mismatches,
                                      "node_reduction_vs_original_full": 1 - nodes / measurements["full"]["nodes"]}
            output["solver_suit_canonicalization"] = canon_result
    return output


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    scoped = [AI / p for p in ("tuppi_ai/best.py", "tuppi_ai/search.py", "native/tuppi_core.h",
                              "native/tuppi_core.c", "native/tuppi_env.c", "native/tuppi_dd.c",
                              "native/tuppi_mlp.c", "native/libtuppi.dylib", "models/equity_incumbent.json")]
    before = {str(p.relative_to(ROOT)): sha(p) for p in scoped}
    lib = load_native()
    states = corpus(lib)
    manifest = json.loads((ASSETS / "models.json").read_text())
    start = time.perf_counter()
    result = {"schema": "tuppi.cheap_wins.mechanism_probes.v1", "synthetic_unforced_states": len(states),
              "adaptive_anchor": adaptive_probe(), "suit_symmetry": symmetry_probe(lib, states, manifest, "Random-legal synthetic ordinary v3 states"),
              "suit_symmetry_actor_trajectories": symmetry_probe(lib, actor_corpus(lib, manifest), manifest,
                    "Native VRPO3-greedy synthetic v3 trajectories with all sooli offers declined; not current searched-bot self-play"),
              "equity_tail": tail_probe(lib, states)}
    result["wall_seconds"] = time.perf_counter() - start
    result["source_hashes"] = before
    result["source_unchanged_during_probes"] = before == {str(p.relative_to(ROOT)): sha(p) for p in scoped}
    assert result["source_unchanged_during_probes"]
    (OUT / "PROBES.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "source_hashes"}, indent=2))


if __name__ == "__main__":
    main()
