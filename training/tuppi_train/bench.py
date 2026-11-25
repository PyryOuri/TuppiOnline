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


def run(policy: str, games: int, games_per_iter: int, offer_model: str | None, dev: torch.device) -> dict:
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
        if dev.type == "cuda":
            torch.cuda.synchronize()
        t = time.perf_counter()
        row = learner.update(d)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        dt = time.perf_counter() - t
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
    return out


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--policy", default=str(MODELS / "vrpo4_final.pt"))
    p.add_argument("--games", type=int, default=None, help="deals per measurement (default 16384 on a GPU, 1024 on a CPU)")
    p.add_argument("--games-per-iter", type=int, default=16384)
    p.add_argument("--offer-model", default=None)
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    dev = device.pick(a.device)
    games = a.games or (16384 if dev.type == "cuda" else 1024)
    print(json.dumps(run(a.policy, games, a.games_per_iter, a.offer_model, dev), indent=1), flush=True)


if __name__ == "__main__":
    main()
