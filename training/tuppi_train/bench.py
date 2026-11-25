"""Throughput of every stage on this machine, to decide how to train on it.

    python -m tuppi_train.bench                       # sizes chosen for the device
    python -m tuppi_train.bench --offer-model training/runs/offer/offer_model.pt

Prints one JSON object. The numbers that matter:

  native_rows_s       C rollouts with the network on the CPU (what vrpo.py used), 1 and all threads
  engine_exact_offers the engine alone (sooli + encoding), no network: the ceiling of the collector
  lockstep_rows_s     lockstep rollouts with the network on the device
  update_rows_s       the learner's update (4 critic + 4 actor epochs)
  iteration_s         projected seconds per iteration of `--games-per-iter` deals, for the lockstep
                      collector and for the native one; iterations_per_hour likewise

`--sweep` adds what the training options buy on this machine, all on the same rollouts and
the same trained weights:

  sweep.precision     for float32, float32 with TF32, bf16, fp16 and the best of them compiled:
                      update speed, and how far the option moves what the learner computes
                      (correlation and relative error of the advantages against plain float32,
                      share of decisions where the greedy action stays the same)
  sweep.recommended   the fastest option that leaves those essentially unchanged
  sweep.shape         projected iteration time and deals per hour for batch sizes and epoch
                      counts, from a measured fixed cost and cost per epoch. Speed only: whether
                      fewer epochs on more deals learns better is a training experiment.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import os
import tempfile
import time

import torch

from . import MODELS, device, lockstep, offer, tn, vrpo_gpu
from tuppi_ai import model as qmodel
from tuppi_ai import native

RULESET = 3


def _env(n, encoder):
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    env = native.Env(n, 1, Equity.load(EQUITY).table, single_deal=True, encoder=encoder)
    env.set_sooli(0, False, False, 0.0)
    return env


def _sync(dev) -> None:
    if dev.type == "cuda":
        torch.cuda.synchronize()


def _timed_update(learner, d, dev) -> tuple[dict, float]:
    _sync(dev)
    t = time.perf_counter()
    row = learner.update({k: v.copy() for k, v in d.items()})
    _sync(dev)
    return row, time.perf_counter() - t


def sweep(policy: str, d: dict, games: int, dev: torch.device, tmp: str, offer=None) -> dict:
    """Precision, compilation, batch size and epochs on the rollouts `d` (see the module docstring)."""
    enc = 2
    n = len(d["action"])

    def learner(name, **extra):
        cfg = vrpo_gpu.Config(**{**dict(init=policy, panel="", games_per_iter=games, warmup_max=0, actor_ramp=0,
                                        eval_base=8, milestone_every=0, max_kl=1e9), **extra})
        return vrpo_gpu.Learner(cfg, f"{tmp}/{name}", dev, resume=False)

    # weights to compare on: one plain float32 update, so that the critic is not at its zero start
    base = learner("base", tf32=False)
    base.update({k: v.copy() for k, v in d.items()})
    weights = [{k: v.detach().clone() for k, v in net.state_dict().items()} for net in (base.actor, base.critic)]
    del base

    variants = [("float32", dict(tf32=False))]
    if dev.type == "cuda":
        variants.append(("float32+tf32", dict(tf32=True)))
    variants += [("bf16", dict(amp="bf16")), ("fp16", dict(amp="fp16"))]
    sample = slice(0, min(n, 131072))
    out, ref_adv, ref_greedy = [], None, None
    for name, extra in variants:
        row = {"name": name, **extra}
        try:
            L = learner(name, **extra)
            L.actor.load_state_dict(weights[0])
            L.critic.load_state_dict(weights[1])
            chooser = lockstep.TorchGreedy(L.actor, dev, enc, amp=L.amp)
            greedy = chooser(d["feat"][sample], d["mask"][sample], None, None)[0]
            stats, dt = _timed_update(L, d, dev)
            adv = L.last["adv"].detach().float().cpu()
            if ref_adv is None:
                ref_adv, ref_greedy = adv, greedy
            row.update(update_rows_s=round(n / dt), update_s=round(dt, 2),
                       adv_correlation=float(torch.corrcoef(torch.stack([adv, ref_adv]))[0, 1]),
                       adv_relative_error=float((adv - ref_adv).abs().mean() / ref_adv.std()),
                       greedy_agreement=float((greedy == ref_greedy).mean()),
                       logp_shift=stats["logp_shift"], kl=stats["kl"])
            del L
        except Exception as error:  # an option this GPU or this torch does not support
            row["error"] = f"{type(error).__name__}: {str(error)[:200]}"
        out.append(row)
        if dev.type == "cuda":
            torch.cuda.empty_cache()
    usable = [r for r in out if "error" not in r and r["adv_correlation"] >= 0.999 and r["greedy_agreement"] >= 0.998]
    best = max(usable, key=lambda r: r["update_rows_s"])
    best_extra = {k: best[k] for k in ("tf32", "amp") if k in best}

    # compilation on the best precision: the first update pays for compiling, the second shows the gain
    comp = {"name": best["name"] + "+compile", **best_extra, "compile": True}
    try:
        L = learner("compiled", compile=True, **best_extra)
        L.actor.load_state_dict(weights[0])
        L.critic.load_state_dict(weights[1])
        _, first = _timed_update(L, d, dev)
        _, steady = _timed_update(L, d, dev)
        comp.update(update_rows_s=round(n / steady), update_s=round(steady, 2), first_update_s=round(first, 1))
        del L
    except Exception as error:
        comp["error"] = f"{type(error).__name__}: {str(error)[:200]}"
    out.append(comp)
    use_compile = "error" not in comp and comp["update_rows_s"] > 1.1 * best["update_rows_s"]
    chosen = comp if use_compile else best

    # epochs: one more timing with a single epoch each gives the fixed cost and the cost per epoch
    L = learner("one", actor_epochs=1, critic_epochs=1, compile=use_compile, **best_extra)
    if use_compile:
        _timed_update(L, d, dev)
    _, t1 = _timed_update(L, d, dev)
    del L
    t4 = chosen["update_s"]
    per_epoch = max(1e-9, (t4 - t1) / 3)          # seconds per (critic + actor) epoch on n rows
    fixed = max(0.0, t1 - per_epoch)               # targets, transfers
    rows_per_deal = n / games
    # self-play in the chosen precision, at this batch size and at four times it: each lockstep
    # step has a fixed cost that a larger batch spreads over more rows
    sampler = lockstep.TorchSampler(qmodel.load(policy, dev), dev, 1.0, device.generator(dev, 1), enc,
                                    amp=device.AMP[best_extra.get("amp", "off")])
    native.set_offer_model(offer)
    play = {}
    for g in (games, 4 * games):
        tm: dict = {}
        lockstep.rollouts(_env(g, enc), sampler, g, RULESET, C.c_uint64(8), enc, timing=tm)
        play[g] = tm["rows"] / tm["total"]
    native.set_offer_model(None)
    shape = []
    for g in (games, 4 * games):
        for epochs in (4, 2, 1):
            rows = g * rows_per_deal
            sec = rows / play[g] + (fixed + epochs * per_epoch) * rows / n
            shape.append({"games_per_iter": g, "epochs": epochs, "iteration_s": round(sec, 1),
                          "deals_per_hour": round(3600 / sec * g), "rows_trained_per_hour": round(3600 / sec * rows * epochs),
                          "learner_share": round(1 - (rows / play[g]) / sec, 2)})
    args = []
    if best_extra.get("amp"):
        args += ["--amp", best_extra["amp"]]
    if best_extra.get("tf32") is False:
        args += ["--tf32", "false"]
    if use_compile:
        args += ["--compile", "true"]
    return {"precision": out, "recommended": {"name": chosen["name"], "args": " ".join(args),
                                              "update_rows_s": chosen["update_rows_s"]},
            "lockstep_rows_s_in_that_precision": {str(g): round(v) for g, v in play.items()},
            "update_fixed_s": round(fixed, 2), "update_s_per_epoch": round(per_epoch, 2), "shape": shape}


def run(policy: str, games: int, games_per_iter: int, offer_model: str | None, dev: torch.device,
        do_sweep: bool = False) -> dict:
    device.setup(dev)
    torch.manual_seed(0)
    net = qmodel.load(policy, dev)
    enc = net.encoder
    cpu_net = qmodel.load(policy, "cpu")
    mlp = native.Mlp(cpu_net)
    cores = len(os.sched_getaffinity(0))
    out = {"machine": device.describe(dev), "threads": tn.threads(), "policy": os.path.basename(policy),
           "games": games, "offer_model": bool(offer_model)}
    native.set_rollout_chunk(128)

    # 1. native rollouts, network on the CPU
    def native_rate(n, threads):
        tn.set_threads(threads)
        env = _env(n, enc)
        env.set_incremental(True, net.config["width"])
        t = time.perf_counter()
        d = native.ppo_rollouts(env, mlp, n, RULESET, C.c_uint64(3))
        return d, len(d["action"]) / (time.perf_counter() - t)

    small = max(256, games // 8)
    _, r1 = native_rate(small, 1)
    recorded, rn = native_rate(games, cores)
    out["native_rows_s"] = {"1": round(r1), str(cores): round(rn)}
    rows_per_deal = len(recorded["action"]) / games
    out["rows_per_deal"] = round(rows_per_deal, 2)

    # 2. the engine alone: replay those actions (no network), with the exact offer heuristic
    native.set_offer_model(None)
    tm: dict = {}
    lockstep.rollouts(_env(games, enc), lockstep.Replay(recorded, games), games, RULESET, C.c_uint64(3), enc,
                      burn_rng=True, timing=tm)
    out["engine_exact_offers"] = {"rows_s": round(tm["rows"] / (tm["sooli"] + tm["encode"])),
                                  "sooli_share": round(tm["sooli"] / (tm["sooli"] + tm["encode"]), 3),
                                  "sooli_ms_per_deal": round(1000 * tm["sooli"] / games, 4),
                                  "encode_rows_s": round(tm["rows"] / tm["encode"])}

    # 3. lockstep rollouts with the network on the device
    def lock(model):
        native.set_offer_model(model)
        sampler = lockstep.TorchSampler(net, dev, 1.0, device.generator(dev, 1), enc)
        lockstep.rollouts(_env(256, enc), sampler, 256, RULESET, C.c_uint64(5), enc)  # warm up
        tm: dict = {}
        d = lockstep.rollouts(_env(games, enc), sampler, games, RULESET, C.c_uint64(4), enc, timing=tm)
        return d, {"rows_s": round(tm["rows"] / tm["total"]), "split_s": {k: round(tm[k], 3) for k in
                                                                         ("total", "choose", "sooli", "encode")}}

    d, out["lockstep_exact_offers"] = lock(None)
    om = offer.load_native(offer_model) if offer_model else None
    if om is not None:
        d, out["lockstep_offer_model"] = lock(om)
    native.set_offer_model(None)

    # 4. the learner's update on those rollouts
    with tempfile.TemporaryDirectory() as tmp:
        cfg = vrpo_gpu.Config(init=policy, panel="", games_per_iter=games, warmup_max=0, actor_ramp=0,
                              eval_base=8, milestone_every=0)
        learner = vrpo_gpu.Learner(cfg, tmp, dev, resume=False)
        row, dt = _timed_update(learner, d, dev)
        del learner
        out["update_rows_s"] = round(row["rows"] / dt)
        out["update_epochs"] = {"critic": cfg.critic_epochs, "actor": row["epochs"]}
        if dev.type == "cuda":
            out["gpu_peak_gb"] = round(torch.cuda.max_memory_allocated() / 2**30, 2)

        # 5. evaluation: paired duplicate of the policy against itself
        base = max(32, games // 16)
        tm = {}
        g = lockstep.TorchGreedy(net, dev, enc)
        lockstep.duplicate_eval(_env(8 * base, enc), g, g, base, RULESET, C.c_uint64(9), enc, timing=tm)
        out["eval_deals_s"] = round(8 * base / tm["total"])

    rows = games_per_iter * rows_per_deal
    best = out.get("lockstep_offer_model", out["lockstep_exact_offers"])["rows_s"]
    proj = {"lockstep": rows / best + rows / out["update_rows_s"],
            "native": rows / rn + rows / out["update_rows_s"]}
    out["iteration_s"] = {k: round(v, 1) for k, v in proj.items()}
    out["iterations_per_hour"] = {k: round(3600 / v) for k, v in proj.items()}
    out["deals_per_hour"] = {k: round(3600 / v * games_per_iter) for k, v in proj.items()}
    if do_sweep:
        with tempfile.TemporaryDirectory() as tmp:
            out["sweep"] = sweep(policy, d, games, dev, tmp, om)
    return out


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--policy", default=str(MODELS / "vrpo4_final.pt"))
    p.add_argument("--games", type=int, default=None, help="deals per measurement (default 16384 on a GPU, 1024 on a CPU)")
    p.add_argument("--games-per-iter", type=int, default=16384)
    p.add_argument("--offer-model", default=None)
    p.add_argument("--device", default=None)
    p.add_argument("--sweep", action="store_true", help="also measure precision, compilation, batch size, epochs")
    a = p.parse_args(argv)
    dev = device.pick(a.device)
    games = a.games or (16384 if dev.type == "cuda" else 1024)
    print(json.dumps(run(a.policy, games, a.games_per_iter, a.offer_model, dev, a.sweep), indent=1), flush=True)


if __name__ == "__main__":
    main()
