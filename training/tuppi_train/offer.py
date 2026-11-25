"""The fast sooli-offer model for self-play, rebuilt from the exact heuristic.

`tuppi_ai/offer_screen.py` describes the model: when a defender's hand passes
the offer prefilter, the exact heuristic solves up to eight sampled worlds, and
that is most of the CPU of real-rules self-play. A small network predicts the
heuristic's answer from the defender's observation; with it set
(`native.set_offer_model`), the engine accepts with the predicted probability.

The original `models/offer_model_selfplay.pt` and its data generator are not in
this repository, so this module regenerates both: offers met in self-play of a
policy network, labelled by the exact heuristic (the engine records them while
it resolves them: tc_ls_observe), then `offer_screen.train` and
`offer_screen.calibrate`.

    python -m tuppi_train.offer --out training/runs/offer --offers 400000
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from pathlib import Path

import numpy as np
import torch

from . import MODELS, device, lockstep, tn
from tuppi_ai import model as qmodel
from tuppi_ai import native


def _env(games: int, encoder: int, seed: int = 1) -> "native.Env":
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    env = native.Env(games, seed, Equity.load(EQUITY).table, single_deal=True, encoder=encoder)
    env.set_sooli(0, False, False, 0.0)
    return env


def record(net, dev, offers: int, games: int = 8192, seed: int = 1, ruleset: int = 3, temperature: float = 1.0,
           offer_model: "native.Mlp | None" = None) -> dict:
    """Self-play of `net` until at least `offers` prefiltered offers have been answered (by the exact
    heuristic, or by `offer_model` if given). Returns their packed encoder-1 observations and
    answers, plus the deal counts of the games played."""
    native.set_offer_model(offer_model)
    env = _env(games, net.encoder, seed)
    sampler = lockstep.TorchSampler(net, dev, temperature, device.generator(dev, seed + 5), net.encoder)
    cap = offers + 4 * games
    feat, label = np.zeros((cap, tn.FEAT1_BYTES), np.uint8), np.zeros(cap, np.uint8)
    counter, rng = C.c_int(0), C.c_uint64(seed * 0x9E3779B97F4A7C15 % 2**64 + 29)
    deals, counts, t0, sooli_s = 0, {"done": 0, "rami": 0, "sooli": 0, "team0_wins": 0}, time.perf_counter(), 0.0
    while counter.value < offers:
        timing: dict = {}
        lockstep.rollouts(env, sampler, games, ruleset, rng, net.encoder, offers=(feat, label, counter), timing=timing)
        deals += games
        sooli_s += timing["sooli"]
        for key, value in tn.summary(env, games).items():
            counts[key] += value
    n = min(counter.value, cap)
    return {"feat": feat[:n], "label": label[:n], "deals": deals, "counts": counts,
            "seconds": time.perf_counter() - t0, "sooli_seconds": sooli_s}


def build(out: Path, net=None, dev=None, offers: int = 400000, val_share: float = 0.1, games: int = 8192,
          seed: int = 1, steps: int = 6000) -> dict:
    """Generates the data, trains and calibrates the model; writes `out/offer_model.pt`."""
    from tuppi_ai import offer_screen
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    dev = dev or device.pick()
    net = net or qmodel.load(MODELS / "vrpo4_final.pt", dev)
    data = record(net, dev, offers, games, seed)
    n = len(data["label"])
    order = np.random.default_rng(seed).permutation(n)
    n_val = max(1, int(n * val_share))
    for name, sel in (("val", order[:n_val]), ("train", order[n_val:])):
        np.savez(out / f"{name}.npz", feat=data["feat"][sel], label=data["label"][sel])
    summary = offer_screen.train(out / "train.npz", out / "val.npz", out / "offer_raw.pt", steps=steps, device=str(dev))
    summary["calibration"] = offer_screen.calibrate(out / "offer_raw.pt", out / "val.npz", out / "offer_model.pt")
    summary.update(offers=n, deals=data["deals"], offers_per_deal=n / data["deals"],
                   accept_rate=float(data["label"].mean()), generate_seconds=round(data["seconds"], 1),
                   sooli_seconds=round(data["sooli_seconds"], 1))
    (out / "offer_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def load_native(path) -> "native.Mlp":
    from tuppi_ai.offer_screen import load
    om, _ = load(path)
    return native.Mlp(om, in_dim=om.config["in_dim"], out_dim=1)


def validate(model_path, net=None, dev=None, offers: int = 20000, games: int = 8192, seed: int = 99) -> dict:
    """The model against the exact heuristic on fresh self-play: acceptance rate among prefiltered
    offers and the share of deals in which a sooli is played, with z-scores of the differences,
    and how much engine time the model saves."""
    dev = dev or device.pick()
    net = net or qmodel.load(MODELS / "vrpo4_final.pt", dev)
    exact = record(net, dev, offers, games, seed)
    model = record(net, dev, offers, games, seed, offer_model=load_native(model_path))
    native.set_offer_model(None)

    def z(p1, n1, p2, n2):
        p = (p1 * n1 + p2 * n2) / (n1 + n2)
        return float((p1 - p2) / max(1e-12, np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))))

    ae, am = float(exact["label"].mean()), float(model["label"].mean())
    se, sm = exact["counts"]["sooli"] / exact["deals"], model["counts"]["sooli"] / model["deals"]
    return {"accept_exact": ae, "accept_model": am, "accept_z": z(ae, len(exact["label"]), am, len(model["label"])),
            "sooli_share_exact": se, "sooli_share_model": sm, "sooli_z": z(se, exact["deals"], sm, model["deals"]),
            "offers": [len(exact["label"]), len(model["label"])], "deals": [exact["deals"], model["deals"]],
            "sooli_ms_per_deal_exact": 1000 * exact["sooli_seconds"] / exact["deals"],
            "sooli_ms_per_deal_model": 1000 * model["sooli_seconds"] / model["deals"]}


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--offers", type=int, default=400000)
    p.add_argument("--games", type=int, default=8192)
    p.add_argument("--steps", type=int, default=6000)
    p.add_argument("--policy", default=str(MODELS / "vrpo4_final.pt"))
    p.add_argument("--device", default=None)
    a = p.parse_args(argv)
    dev = device.pick(a.device)
    device.setup(dev)
    net = qmodel.load(a.policy, dev)
    print(json.dumps(build(a.out, net, dev, a.offers, games=a.games, steps=a.steps), indent=1), flush=True)
    print(json.dumps(validate(a.out / "offer_model.pt", net, dev, games=a.games), indent=1), flush=True)


if __name__ == "__main__":
    main()
