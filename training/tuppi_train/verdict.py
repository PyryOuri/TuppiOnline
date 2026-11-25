"""Stage 1 of the label-based attempt: is there a learnable gain over VRPO4?

    python -m tuppi_train.verdict --out <dir> --hours 1.5 --offer-model <offer_model.pt>

One command, any number of sessions: every step writes its result under <dir>
and is skipped when that result exists. Run it again until it prints the
verdict. What it does, for the main network (VRPO4) and for a control (VRPO3,
which is known to be improvable, since VRPO4 exists):

1. data      self-play decisions, each labelled two ways from the same states:
             q0 = own play to the end, q6 = solver tail from 6 tricks out;
2. teachers  Q networks fitted to each label kind: one of the policy's own
             shape started from its weights (and, for the main network, at
             four data sizes: the learning curve), one larger from scratch;
3. margins   per teacher, the correction thresholds for showing and for card
             play with the best held-out one-step gain on clean states. A
             phase is corrected only if that gain is significantly positive;
4. direct    without a teacher: a copy of the policy trained by small steps
             to choose better on the labels themselves (improve.fit_policy);
5. select    every candidate (a teacher's composite, or a directly improved
             network) plays the policy itself; the best one of the main
             network is then
6. confirm   played on fresh deals: in full, restricted to decisions with more
             than 6 tricks to go, and against the other shipped networks.

The verdict is GO (with the label kind to use), STOP (the method lifts the
control but not the main network) or INCONCLUSIVE (it does not lift the control
either, so a null result says nothing about the main network).
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import time
import zlib
from pathlib import Path

import numpy as np
import torch

from . import MODELS, device, improve, labels, lockstep, offer, tn
from .vrpo_gpu import resolve_model
from tuppi_ai import model as qmodel
from tuppi_ai import native

KINDS = {"q0": 0, "q6": 6}                       # label column -> solver tail (tricks)
SHOW_MARGINS = (0.006, 0.012, 0.03, 0.06, 0.12)  # equity; Heidi keeps a bid unless search beats it by 0.03
PLAY_MARGINS = (0.003, 0.006, 0.012, 0.03, 0.06)  # ... and a card unless by 0.003
OFF = 1e6                                         # a margin no teacher overcomes: that phase is left alone
GATE_Z = 2.0                                      # a correction must gain this many standard errors (selfplay.py)
RULESET = 3


def stable_seed(*parts) -> int:
    return zlib.crc32("/".join(str(p) for p in parts).encode()) + 1


def atomic_npz(path: Path, **arrays) -> None:
    tmp = path.with_name(path.name + ".tmp.npz")
    np.savez(tmp, **arrays)
    os.replace(tmp, path)


def class_multipliers(ids: np.ndarray, q: np.ndarray, cls: np.ndarray, min_states: int = 200) -> np.ndarray:
    """Recording multipliers per position class from a shard recorded with multiplier 1: a class
    is recorded in proportion to its share of non-inert decisions (those where the actions'
    labels differ), within [0.25, 2]; classes with fewer than `min_states` states keep 1
    (selfplay.py `_update_class_mult`)."""
    valid = ids != labels.PAD
    qf = q.astype(np.float32)
    inert = np.where(valid, qf, -np.inf).max(1) == np.where(valid, qf, np.inf).min(1)
    overall = max(1.0 - inert.mean(), 1e-6)
    mult = np.ones(labels.N_CLASSES)
    for c in range(labels.N_CLASSES):
        m = cls == c
        if m.sum() >= min_states:
            mult[c] = (1.0 - inert[m].mean()) / overall
    return np.clip(mult, 0.25, 2.0)


class Run:
    def __init__(self, a):
        self.a, self.out = a, Path(a.out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.dev = device.pick(a.device)
        device.setup(self.dev)
        self.amp = device.AMP[a.amp]
        self.t_end = time.time() + 3600 * a.hours
        self.results_path = self.out / "results.json"
        self.results = json.loads(self.results_path.read_text()) if self.results_path.exists() else {}
        self.nets: dict = {}
        self.envs: dict = {}
        from tuppi_ai.best import EQUITY
        from tuppi_ai.equity import Equity
        self.table = Equity.load(EQUITY).table
        # process-wide engine settings of this run, set and recorded on every start
        self.settings = {"offer_model": bool(a.offer_model), "branch_share": False, "dd_extra_nolo": 0,
                         "ruleset": RULESET, "amp": a.amp, "gate_z": a.gate_z}
        self.offer = offer.load_native(a.offer_model) if a.offer_model else None
        native.set_offer_model(self.offer)
        native.set_branch_share(False)
        native.lib.tc_set_dd_extra_nolo(0)
        saved = self.results.get("settings")
        if saved is not None and saved != self.settings:
            raise SystemExit(f"this run was started with {saved}; now {self.settings}. Use the same options, "
                             "or another --out.")
        self.results["settings"] = self.settings
        self.results.setdefault("machine", device.describe(self.dev))

    # ------------------------------------------------------------- helpers
    def time_left(self) -> bool:
        return time.time() < self.t_end

    def save(self) -> None:
        tmp = self.results_path.with_name("results.json.tmp")
        tmp.write_text(json.dumps(self.results, indent=1))
        os.replace(tmp, self.results_path)

    def log(self, *parts) -> None:
        print(*parts, flush=True)

    def net(self, name: str):
        if name not in self.nets:
            self.nets[name] = qmodel.load(resolve_model(name), self.dev)
        return self.nets[name]

    def env(self, n: int) -> "native.Env":
        if n not in self.envs:
            e = native.Env(n, 1, self.table, single_deal=True, encoder=2)
            e.set_sooli(0, False, False, 0.0)
            self.envs[n] = e
        return self.envs[n]

    def greedy(self, net):
        return lockstep.TorchGreedy(net, self.dev, net.encoder, amp=self.amp)

    # ---------------------------------------------------------------- data
    def shard_path(self, tag: str, i: int) -> Path:
        return self.out / "data" / tag / f"shard_{i:03d}.npz"

    def n_shards(self, tag: str) -> int:
        states = self.a.states if tag == "main" else self.a.control_states
        return max(2, -(-states // self.a.shard_states))

    def class_mult(self, tag: str) -> np.ndarray:
        z = np.load(self.shard_path(tag, 0))
        return class_multipliers(z["ids"], z["q0"], z["cls"])

    def make_shard(self, tag: str, model: str, i: int) -> None:
        a = self.a
        net = self.net(model)
        choose = self.greedy(net)
        mult = np.ones(labels.N_CLASSES) if i == 0 else self.class_mult(tag)
        env_play, env_label = self.env(a.games), self.env(a.label_slots)
        rng = C.c_uint64(stable_seed(a.seed, tag, i, "deals"))
        parts, n, batch, t0 = [], 0, 0, time.perf_counter()
        timing = {"play": 0.0, "q0": 0.0, "q6": 0.0, "solver": 0.0, "rows_q0": 0, "rows_q6": 0}
        while n < a.shard_states:
            t = time.perf_counter()
            d = labels.collect(env_play, choose, a.games, rng, a.p_record, a.p_explore, mult,
                               seed=stable_seed(a.seed, tag, i, batch, "record"))
            timing["play"] += time.perf_counter() - t
            m = len(d["states"])
            seeds = labels.state_seeds(m, stable_seed(a.seed, tag, i, batch, "labels"))
            counts = np.unpackbits(d["mask"], axis=1).sum(1)
            part = {"feat": d["feat"], "cls": d["cls"], "explored": d["explored"],
                    "w": (1.0 / mult[d["cls"]]).astype(np.float32)}
            for kind, dd in KINDS.items():
                tm: dict = {}
                ids, q = labels.branch_labels(env_label, d["states"], choose, seeds, dd, timing=tm, counts=counts)
                part["ids"], part[kind] = ids, q
                timing[kind] += tm["total"]
                timing["rows_" + kind] += tm["rows"]
                timing["solver"] += tm["solver"]
            parts.append(part)
            n += m
            batch += 1
        data = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
        path = self.shard_path(tag, i)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_npz(path, **data, mult=mult)
        sec = time.perf_counter() - t0
        info = {"states": int(n), "deals": batch * a.games, "seconds": round(sec, 1),
                "states_per_s": round(n / sec), **{k: round(v, 1) for k, v in timing.items()}}
        self.results.setdefault("data", {}).setdefault(tag, {})[str(i)] = info
        self.save()
        self.log(f"data {tag} shard {i + 1}/{self.n_shards(tag)}: {n:,} states in {sec:.0f}s "
                 f"({info['states_per_s']:,}/s; play {timing['play']:.0f}s, own-play labels {timing['q0']:.0f}s, "
                 f"solver-tail labels {timing['q6']:.0f}s of which solver {timing['solver']:.0f}s)")

    def load_data(self, tag: str) -> tuple[dict, dict]:
        """(training rows, held-out rows) on the device. The last tenth of the shards (whole deals,
        never seen by a teacher) is held out; weights are normalised to mean 1."""
        k = self.n_shards(tag)
        hold_from = k - max(1, k // 10)
        sets = []
        for part in (range(hold_from), range(hold_from, k)):
            z = [np.load(self.shard_path(tag, i)) for i in part]
            d = {key: np.concatenate([s[key] for s in z]) for key in ("feat", "ids", "q0", "q6", "cls", "explored", "w")}
            d["w"] = (d["w"] / d["w"].mean()).astype(np.float16)
            sets.append(improve.to_device(d, self.dev))
        return sets[0], sets[1]

    # ------------------------------------------------------------ teachers
    def teacher_path(self, key: str) -> Path:
        return self.out / "teachers" / f"{key}.pt"

    def load_teacher(self, key: str):
        return qmodel.load(self.teacher_path(key), self.dev)

    def fit(self, key: str, policy, D: dict, H: dict, kind: str, arch: str, rows: int | None) -> None:
        a = self.a
        torch.manual_seed(stable_seed(a.seed, key))
        if arch == "warm":
            teacher = improve.new_teacher(0, 0, policy.encoder, self.dev, warm_from=policy)
            steps, lr = a.warm_steps, 1e-3
        else:
            teacher = improve.new_teacher(a.big_width, a.big_blocks, policy.encoder, self.dev)
            steps, lr = a.big_steps, 5e-4
        T = D if rows is None else improve.take(D, torch.arange(min(rows, len(D["feat"])), device=self.dev))
        fit = improve.fit_teacher(teacher, T, H, steps=steps, batch=min(a.batch, len(T["feat"])), lr=lr, amp=self.amp,
                                  compile_net=a.compile, check_every=a.check_every, patience=a.patience, label=kind)
        teacher.eval()
        # Margins: the two phases touch disjoint rows, so each is chosen on its own.
        gains = {"show": {}, "play": {}}
        for m in SHOW_MARGINS:
            gains["show"][str(m)] = improve.heldout_gain(policy, teacher, H, m, OFF, kind, True, amp=self.amp)
        for m in PLAY_MARGINS:
            gains["play"][str(m)] = improve.heldout_gain(policy, teacher, H, OFF, m, kind, True, amp=self.amp)
        # ... and corrected only if its best margin gains significantly on held-out states. A
        # teacher's argmax over noisy estimates otherwise changes many decisions for the worse.
        chosen = {}
        for phase, g in gains.items():
            ok = [m for m in g if g[m]["z"] >= self.a.gate_z]
            chosen[phase] = float(max(ok, key=lambda m: g[m]["gain"])) if ok else OFF
        ms, mp = chosen["show"], chosen["play"]
        info = {"kind": kind, "arch": arch, "train_states": int(len(T["feat"])), "held_out_states": int(len(H["feat"])),
                "shape": [teacher.config["width"], teacher.config["blocks"]],
                **{k: fit[k] for k in ("adv_r2", "best_step", "steps", "seconds")},
                "margins": [ms, mp], "usable": ms != OFF or mp != OFF, "gains": gains,
                "gain": improve.heldout_gain(policy, teacher, H, ms, mp, kind, True, amp=self.amp),
                "gain_early": improve.heldout_gain(policy, teacher, H, ms, mp, kind, True, 6, amp=self.amp)}
        if kind != "q0":   # the solver-tail teacher judged by the policy's own continuations
            info["gain_on_q0"] = improve.heldout_gain(policy, teacher, H, ms, mp, "q0", True, amp=self.amp)
        path = self.teacher_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        qmodel.save(teacher, tmp, verdict=info)
        os.replace(tmp, path)
        self.results.setdefault("teachers", {})[key] = info
        self.save()
        g = info["gain"]
        show = lambda m: "off" if m == OFF else m   # noqa: E731
        self.log(f"teacher {key}: R2 {fit['adv_r2']:.4f} at step {fit['best_step']} ({fit['seconds']:.0f}s); margins "
                 f"show {show(ms)} play {show(mp)}; held-out gain {g['gain']:+.6f} +/- {g['se']:.6f} per decision, "
                 f"changes {g['changed']:.2%} of decisions, RAMI bids {g['rami_old']:.3f} -> {g['rami_new']:.3f}")

    # ---------------------------------------------------------------- direct
    def policy_path(self, key: str) -> Path:
        return self.out / "policies" / f"{key}.pt"

    def fit_direct(self, key: str, policy, D: dict, H: dict, kind: str) -> None:
        a = self.a
        torch.manual_seed(stable_seed(a.seed, key))
        net, fit = improve.fit_policy(policy, D, H, kind, steps=a.direct_steps, batch=min(a.batch, len(D["feat"])),
                                      lr=a.direct_lr, amp=self.amp, check_every=a.check_every, patience=a.patience)
        info = {"kind": kind, "train_states": int(len(D["feat"])), "held_out_states": int(len(H["feat"])),
                "usable": fit["best_step"] > 0, **{k: fit[k] for k in ("best_step", "steps", "seconds", "history")},
                "gain": improve.greedy_gain(policy, net, H, kind, True, amp=self.amp),
                "gain_early": improve.greedy_gain(policy, net, H, kind, True, 6, amp=self.amp)}
        if kind != "q0":
            info["gain_on_q0"] = improve.greedy_gain(policy, net, H, "q0", True, amp=self.amp)
        path = self.policy_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        qmodel.save(net, tmp, verdict=info)
        os.replace(tmp, path)
        self.results.setdefault("policies", {})[key] = info
        self.save()
        g = info["gain"]
        self.log(f"direct {key}: best at step {fit['best_step']} of {fit['steps']} ({fit['seconds']:.0f}s); held-out gain "
                 f"{g['gain']:+.6f} +/- {g['se']:.6f} per decision, changes {g['changed']:.2%} of decisions, "
                 f"RAMI bids {g['rami_old']:.3f} -> {g['rami_new']:.3f}")

    # ------------------------------------------------------------- matches
    def side(self, spec: dict, env):
        """The chooser of a candidate: {"type": "plain", "model"}, {"type": "composite", "policy",
        "teacher", "margins", "min_left"} or {"type": "direct", "policy", "net", "min_left"}."""
        if spec["type"] == "plain":
            return self.greedy(self.net(spec["model"]))
        policy = self.net(spec["policy"])
        if spec["type"] == "composite":
            ms, mp = spec["margins"]
            return improve.Composite(policy, self.load_teacher(spec["teacher"]), self.dev, env, ms, mp,
                                     spec.get("min_left", 0), self.amp)
        new = qmodel.load(self.policy_path(spec["net"]), self.dev)
        return improve.Mixed(self.greedy(new), self.greedy(policy), env, spec.get("min_left", 0))

    def match(self, key: str, spec: dict, opponent: str, base: int, seed: int) -> dict:
        """Paired duplicate over `base` base deals: the candidate against `opponent`. Cached under `key`."""
        done = self.results.setdefault("matches", {})
        if key in done:
            return done[key]
        opp = self.net(opponent)
        chunk = min(self.a.eval_chunk, base)
        env = self.env(8 * chunk)
        rng, values, changed, rows, t0 = C.c_uint64(seed), [], 0, 0, time.perf_counter()
        for start in range(0, base, chunk):
            side_a = self.side(spec, env)
            values.append(lockstep.duplicate_eval(env, side_a, self.greedy(opp), min(chunk, base - start), RULESET, rng))
            changed, rows = changed + getattr(side_a, "changed", 0), rows + getattr(side_a, "rows", 0)
        v = np.concatenate(values)
        mean, half = lockstep.interval(v)
        res = {"candidate": spec, "opponent": opponent, "base_deals": base, "seed": seed, "mean": mean, "ci95": half,
               "changed": changed / rows if rows else 0.0, "seconds": round(time.perf_counter() - t0, 1)}
        done[key] = res
        self.save()
        self.log(f"match {key}: {mean:+.5f} +/- {half:.5f} per deal over {base:,} base deals"
                 + (f" (differs from the policy in {res['changed']:.2%} of its decisions)" if rows else ""))
        return res

    # ---------------------------------------------------------------- plan
    def steps(self):
        """The run as an ordered list of (description, is_done, do)."""
        a = self.a
        S = []
        tags = (("main", a.main), ("control", a.control))
        for tag, model in tags:
            for i in range(self.n_shards(tag)):
                S.append((f"data {tag} {i}", lambda t=tag, i=i: self.shard_path(t, i).exists(),
                          lambda t=tag, m=model, i=i: self.make_shard(t, m, i)))
        fits = []   # (key, tag, model, kind, arch, rows)
        for kind in KINDS:
            for rows in a.curve:
                fits.append((f"main_{kind}_warm_{rows}", "main", a.main, kind, "warm", rows))
            fits.append((f"main_{kind}_warm_all", "main", a.main, kind, "warm", None))
            fits.append((f"control_{kind}_warm_all", "control", a.control, kind, "warm", None))
        for kind in KINDS:   # the slow ones last
            fits.append((f"main_{kind}_big_all", "main", a.main, kind, "big", None))
        cache: dict = {}

        def do_fit(key, tag, model, kind, arch, rows):
            if tag not in cache:
                cache.clear()   # one data set on the device at a time
                cache[tag] = self.load_data(tag)
            self.fit(key, self.net(model), *cache[tag], kind, arch, rows)

        def do_direct(key, tag, model, kind):
            if tag not in cache:
                cache.clear()
                cache[tag] = self.load_data(tag)
            self.fit_direct(key, self.net(model), *cache[tag], kind)

        for f in fits[:-2]:
            S.append((f"teacher {f[0]}", lambda k=f[0]: self.teacher_path(k).exists(), lambda f=f: do_fit(*f)))
        for tag, model in tags:
            for kind in KINDS:
                key = f"{tag}_{kind}_direct"
                S.append((f"direct {key}", lambda k=key: self.policy_path(k).exists(),
                          lambda k=key, t=tag, m=model, kind=kind: do_direct(k, t, m, kind)))
        for f in fits[-2:]:
            S.append((f"teacher {f[0]}", lambda k=f[0]: self.teacher_path(k).exists(), lambda f=f: do_fit(*f)))
        S.append(("matches", lambda: "verdict" in self.results, lambda: (cache.clear(), self.matches())))
        return S

    def candidates(self, tag: str, model: str) -> list[tuple[str, dict]]:
        """(name, spec) of everything worth playing for `tag`: each usable teacher's composite at its
        chosen margins and at twice them (more cautious), and each directly improved network."""
        out = []
        for key, t in self.results.get("teachers", {}).items():
            if key.startswith(tag + "_") and key.endswith("_all") and t["usable"]:
                for label, f in (("", 1.0), ("_x2", 2.0)):
                    margins = [m if m == OFF else f * m for m in t["margins"]]
                    out.append((f"{key}{label}", {"type": "composite", "policy": model, "teacher": key, "margins": margins}))
        for key, t in self.results.get("policies", {}).items():
            if key.startswith(tag + "_") and t["usable"]:
                out.append((key, {"type": "direct", "policy": model, "net": key}))
        return out

    def matches(self) -> None:
        a, R = self.a, self.results
        seed_select, seed_confirm = stable_seed(a.seed, "select"), stable_seed(a.seed, "confirm")
        summary = {}
        for tag, model in (("main", a.main), ("control", a.control)):
            self.match(f"{tag}_self", {"type": "plain", "model": model}, model, min(a.select_base, 1024), seed_select)
            cands = self.candidates(tag, model)
            if not cands:   # nothing passed its held-out gate: the policy stays as it is
                summary[tag] = {"candidate": None, "kind": None, "confirm": [0.0, 0.0], "confirm_early_only": [0.0, 0.0],
                                "note": "no teacher correction and no direct step gained on held-out states"}
                continue
            best = None
            for name, spec in cands:
                if not self.time_left():
                    return
                r = self.match(f"select_{name}", spec, model, a.select_base, seed_select)
                if best is None or r["mean"] > best[2]["mean"]:
                    best = (name, spec, r)
            name, spec, sel = best
            if not self.time_left():
                return
            full = self.match(f"confirm_{tag}", spec, model, a.confirm_base, seed_confirm)
            early = self.match(f"confirm_{tag}_early_only", {**spec, "min_left": 6}, model, a.confirm_base, seed_confirm)
            source = R["teachers"][spec["teacher"]] if spec["type"] == "composite" else R["policies"][spec["net"]]
            summary[tag] = {"candidate": name, "spec": spec, "kind": source["kind"], "select": [sel["mean"], sel["ci95"]],
                            "confirm": [full["mean"], full["ci95"]], "confirm_early_only": [early["mean"], early["ci95"]]}
        if not self.time_left():
            return
        m = summary["main"]
        others = {}
        if m["candidate"]:
            for opp in a.panel.split(","):
                opp = opp.strip()
                if opp and opp != a.main:
                    stem = Path(opp).stem
                    plain = self.match(f"plain_vs_{stem}", {"type": "plain", "model": a.main}, opp, a.panel_base, seed_confirm)
                    cand = self.match(f"candidate_vs_{stem}", m["spec"], opp, a.panel_base, seed_confirm)
                    others[stem] = {"plain": [plain["mean"], plain["ci95"]], "candidate": [cand["mean"], cand["ci95"]]}
        m["against_others"] = others
        won = lambda s: s["confirm"][0] - s["confirm"][1] > 0   # noqa: E731
        ctl = summary["control"]
        if won(m):
            verdict = "GO"
            reason = (f"{m['candidate']} lifts {a.main} by {m['confirm'][0]:+.5f} +/- {m['confirm'][1]:.5f} per deal on "
                      f"fresh deals; with changes only before the last 6 tricks: {m['confirm_early_only'][0]:+.5f} "
                      f"+/- {m['confirm_early_only'][1]:.5f}.")
        elif won(ctl):
            verdict = "STOP"
            reason = (f"the method lifts the control {a.control} ({ctl['confirm'][0]:+.5f} +/- {ctl['confirm'][1]:.5f}, "
                      f"{ctl['candidate']}) but not {a.main} ({m['confirm'][0]:+.5f} +/- {m['confirm'][1]:.5f}).")
        else:
            verdict = "INCONCLUSIVE"
            reason = (f"no gain on {a.main} ({m['confirm'][0]:+.5f} +/- {m['confirm'][1]:.5f}), but none on the control "
                      f"{a.control} either ({ctl['confirm'][0]:+.5f} +/- {ctl['confirm'][1]:.5f}), so the method "
                      "itself is in doubt.")
        R["verdict"] = {"verdict": verdict, "reason": reason, **summary}
        self.save()

    # -------------------------------------------------------------- report
    def report(self) -> None:
        R = self.results
        self.log("\n================ verdict run ================")
        for tag in ("main", "control"):
            shards = R.get("data", {}).get(tag, {})
            if shards:
                n = sum(s["states"] for s in shards.values())
                self.log(f"data {tag}: {n:,} states in {len(shards)}/{self.n_shards(tag)} shards")
        T = R.get("teachers", {})
        if T:
            self.log("\nteacher                       train states   adv R2   margins show/play   gain/decision (z)   early-only gain   changed   RAMI old>new")
            off = lambda m: "off" if m == OFF else f"{m:g}"   # noqa: E731
            for key, t in T.items():
                g, e = t["gain"], t["gain_early"]
                self.log(f"  {key:<28}{t['train_states']:>12,}  {t['adv_r2']:>7.4f}   {off(t['margins'][0]):>7}/{off(t['margins'][1]):<7}   "
                         f"{g['gain']:+.6f} ({g['z']:+5.1f})   "
                         f"{e['gain']:+.6f} ({e['z']:+5.1f})   {g['changed']:>6.2%}   {g['rami_old']:.3f}>{g['rami_new']:.3f}"
                         + (f"   on own-play labels {t['gain_on_q0']['gain']:+.6f} ({t['gain_on_q0']['z']:+.1f})"
                            if "gain_on_q0" in t else ""))
        P = R.get("policies", {})
        if P:
            self.log("\ndirect                        train states   best step   gain/decision (z)   early-only gain   changed   RAMI old>new")
            for key, t in P.items():
                g, e = t["gain"], t["gain_early"]
                self.log(f"  {key:<28}{t['train_states']:>12,}  {t['best_step']:>9}   {g['gain']:+.6f} ({g['z']:+5.1f})   "
                         f"{e['gain']:+.6f} ({e['z']:+5.1f})   {g['changed']:>6.2%}   {g['rami_old']:.3f}>{g['rami_new']:.3f}"
                         + (f"   on own-play labels {t['gain_on_q0']['gain']:+.6f} ({t['gain_on_q0']['z']:+.1f})"
                            if "gain_on_q0" in t else ""))
        M = R.get("matches", {})
        if M:
            self.log("\nmatch                                   per deal            base deals   decisions changed")
            for key, m in M.items():
                self.log(f"  {key:<38}{m['mean']:+.5f} +/- {m['ci95']:.5f}   {m['base_deals']:>8,}   {m['changed']:>7.2%}")
        if "verdict" in R:
            self.log(f"\nVERDICT: {R['verdict']['verdict']}: {R['verdict']['reason']}")
        else:
            self.log("\nnot finished: run the same command again to continue.")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--hours", type=float, default=1.5)
    p.add_argument("--offer-model", default=None)
    p.add_argument("--main", default="vrpo4_final.pt")
    p.add_argument("--control", default="vrpo3_final.pt")
    p.add_argument("--panel", default="vrpo3_final.pt,vrpo1_actor_0504.pt")
    p.add_argument("--states", type=int, default=4_000_000)
    p.add_argument("--control-states", type=int, default=2_000_000)
    p.add_argument("--shard-states", type=int, default=250_000)
    p.add_argument("--curve", type=lambda s: [int(x) for x in s.split(",") if x], default=[500_000, 1_000_000, 2_000_000],
                   help="training-set sizes of the learning curve (the full set is always fitted)")
    p.add_argument("--games", type=int, default=16384)
    p.add_argument("--label-slots", type=int, default=262144)
    p.add_argument("--p-record", type=float, default=0.08)
    p.add_argument("--p-explore", type=float, default=0.01)
    p.add_argument("--warm-steps", type=int, default=3000)
    p.add_argument("--big-steps", type=int, default=8000)
    p.add_argument("--big-width", type=int, default=1536)
    p.add_argument("--big-blocks", type=int, default=6)
    p.add_argument("--gate-z", type=float, default=GATE_Z,
                   help="a teacher's correction of a phase is used only if its held-out gain is this many standard errors")
    p.add_argument("--direct-steps", type=int, default=4000)
    p.add_argument("--direct-lr", type=float, default=2e-5)
    p.add_argument("--batch", type=int, default=16384)
    p.add_argument("--check-every", type=int, default=250)
    p.add_argument("--patience", type=int, default=6)
    p.add_argument("--select-base", type=int, default=16384)
    p.add_argument("--confirm-base", type=int, default=32768)
    p.add_argument("--panel-base", type=int, default=16384)
    p.add_argument("--eval-chunk", type=int, default=4096)
    p.add_argument("--amp", default="fp16", choices=sorted(device.AMP))
    p.add_argument("--compile", type=lambda s: s.lower() in ("1", "true"), default=False)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    run = Run(a)
    run.log(json.dumps({"out": str(run.out), "threads": tn.threads(), **device.describe(run.dev)}))
    for name, is_done, do in run.steps():
        if is_done():
            continue
        if not run.time_left():
            run.log(f"time is up before: {name}")
            break
        do()
    run.report()


if __name__ == "__main__":
    main()
