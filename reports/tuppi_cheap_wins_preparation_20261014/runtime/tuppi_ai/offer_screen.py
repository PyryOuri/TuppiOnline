"""Fast screen for the sooli-offer heuristic (self-play engine speed).

The exact offer heuristic (`tuppi_sooli_policy.c: offer`) solves up to eight
sampled worlds whenever a defender's hand passes its prefilter, which is 57%
of the CPU of real-rules self-play. Only about 2% of those offers are
accepted. This small network predicts the heuristic's decision from the
defender's observation (encoder 1). In the engine, an offer whose predicted
acceptance is below the screen's threshold is declined at once; every other
offer still runs the exact heuristic. The threshold is chosen on held-out
offers for a target recall of accepted offers, so the decisions stay close
to exact while most solves are skipped.

    python tools/gen_offer_data.py --offers 400000 --seed 1 --out runs/offer/train.npz
    python -m tuppi_ai.offer_screen --train runs/offer/train.npz --val runs/offer/val.npz --out runs/offer/screen.pt
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import torch

from . import native
from .value import VNet, _unpack

IN_DIM = native.feature_dim(1)


def train(train_path: Path, val_path: Path, out: Path, width: int = 128, blocks: int = 1, steps: int = 6000,
          batch: int = 4096, lr: float = 2e-3, recall: float = 0.995, device: str | None = None) -> dict:
    dev = torch.device(device or ("mps" if torch.backends.mps.is_available() else "cpu"))
    d, v = np.load(train_path), np.load(val_path)
    x = torch.from_numpy(d["feat"]).to(dev)
    y = torch.from_numpy(d["label"].astype(np.float32)).to(dev)
    xv = _unpack(torch.from_numpy(v["feat"]).to(dev), IN_DIM)
    yv = v["label"].astype(bool)
    net = VNet(width, blocks, in_dim=IN_DIM).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=1e-4, fused=dev.type == "mps")
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=lr, total_steps=steps, pct_start=0.05)
    gen = torch.Generator().manual_seed(0)
    yv_t = torch.from_numpy(yv.astype(np.float32)).to(dev)

    def val_logits():
        net.eval()
        with torch.no_grad():
            out = torch.cat([net(xv[i:i + 65536]) for i in range(0, len(xv), 65536)])
        net.train()
        return out

    best, best_state, history = float("inf"), None, []
    for step in range(1, steps + 1):
        idx = torch.randint(0, len(x), (batch,), generator=gen).to(dev)
        loss = torch.nn.functional.binary_cross_entropy_with_logits(net(_unpack(x[idx], IN_DIM)), y[idx])
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        sched.step()
        if step % 250 == 0 or step == steps:  # early stopping on held-out log-loss (calibration)
            vl = float(torch.nn.functional.binary_cross_entropy_with_logits(val_logits(), yv_t))
            history.append((step, vl))
            if vl < best:
                best, best_state = vl, {k: t.detach().clone() for k, t in net.state_dict().items()}
    net.load_state_dict(best_state)
    net.eval()
    with torch.no_grad():
        logit = torch.cat([net(xv[i:i + 65536]) for i in range(0, len(xv), 65536)]).cpu().numpy()
    pos = np.sort(logit[yv])
    # Threshold: the largest logit that keeps at least `recall` of the accepted offers above it.
    threshold = float(pos[int(math.floor((1 - recall) * len(pos)))]) - 1e-6
    passed = logit >= threshold
    summary = {
        "val_offers": int(len(yv)), "val_accepts": int(yv.sum()), "threshold_logit": threshold,
        "recall": float(passed[yv].mean()), "sent_to_exact": float(passed.mean()),
        "decision_agreement": float(((~passed) & ~yv).sum() + (passed & yv).sum() + (passed & ~yv).sum()) / len(yv),
        "auc": _auc(logit, yv),
        "val_logloss": best, "best_step": min(history, key=lambda h: h[1])[0],
        "constant_logloss": float(-(yv.mean() * math.log(yv.mean()) + (1 - yv.mean()) * math.log(1 - yv.mean()))),
    }
    torch.save({"config": net.config, "state": {k: t.detach().cpu() for k, t in net.state_dict().items()},
                "threshold_logit": threshold, "summary": summary}, out)
    return summary


def _auc(score: np.ndarray, label: np.ndarray) -> float:
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    n1, n0 = label.sum(), (~label).sum()
    return float((ranks[label].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def calibrate(path, val_path: Path, out) -> dict:
    """Platt scaling on held-out offers: logit' = a * logit + b, folded into the
    output layer, so the sampled acceptance rate matches the exact heuristic."""
    net, threshold = load(path)
    v = np.load(val_path)
    x = _unpack(torch.from_numpy(v["feat"]), IN_DIM)
    y = torch.from_numpy(v["label"].astype(np.float32))
    with torch.no_grad():
        z = net(x)
    ab = torch.tensor([1.0, 0.0], requires_grad=True)
    opt = torch.optim.LBFGS([ab], max_iter=200)

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(ab[0] * z + ab[1], y)
        loss.backward()
        return loss

    opt.step(closure)
    a_, b_ = float(ab[0]), float(ab[1])
    with torch.no_grad():
        net.out.weight.mul_(a_)
        net.out.bias.mul_(a_).add_(b_)
    blob = torch.load(path, map_location="cpu", weights_only=False)
    blob["state"] = {k: t.detach().cpu() for k, t in net.state_dict().items()}
    blob["calibration"] = {"a": a_, "b": b_, "fitted_on": str(val_path)}
    torch.save(blob, out)
    return {"a": a_, "b": b_}


def load(path) -> tuple[VNet, float]:
    blob = torch.load(path, map_location="cpu", weights_only=False)
    cfg = blob["config"]
    net = VNet(cfg["width"], cfg["blocks"], in_dim=cfg["in_dim"])
    net.load_state_dict(blob["state"])
    return net.eval(), float(blob["threshold_logit"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--train", type=Path, required=True)
    p.add_argument("--val", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--width", type=int, default=128)
    p.add_argument("--blocks", type=int, default=1)
    p.add_argument("--steps", type=int, default=6000)
    p.add_argument("--recall", type=float, default=0.995)
    a = p.parse_args()
    print(json.dumps(train(a.train, a.val, a.out, a.width, a.blocks, a.steps, recall=a.recall), indent=1))


if __name__ == "__main__":
    main()
