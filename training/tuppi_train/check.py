"""The checks that need the training device itself (run in the notebook).

    python -m tuppi_train.check

The pytest suite runs on the CPU. This one collects rollouts with the sampler on the device
and then checks, on the device:

- consistency: the learner's recomputation of the behaviour log-probabilities, in its own
  shuffled minibatches, equals what the sampler recorded. PPO's ratio is their difference,
  so this must hold whatever the precision setting (TF32) is;
- that a policy against itself evaluates to exactly 0;
- that one full-batch update gives the same statistics as the same update on the CPU from
  the same rollouts (same arithmetic, different rounding).

It also reports how far the device's log-probabilities are from a plain float32 CPU forward
and how well the two updates agree in direction; those are information, not gates.
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import tempfile

import numpy as np
import torch

from . import MODELS, device, lockstep, vrpo_gpu
from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.value import _unpack


def run(dev: torch.device, games: int = 1024, amp: str = "off") -> dict:
    device.setup(dev)
    policy = str(MODELS / "vrpo1_actor_0504.pt")
    cfg = vrpo_gpu.Config(init=policy, panel="vrpo1_actor_0504.pt", games_per_iter=games, minibatch=10**9,
                          critic_width=128, critic_blocks=1, warmup_max=0, actor_ramp=0, eval_base=64,
                          milestone_every=0, max_kl=1e9)
    from dataclasses import replace
    dev_cfg = replace(cfg, amp=amp)   # the device runs the option under test, the CPU plain float32
    with tempfile.TemporaryDirectory() as tmp:
        torch.manual_seed(3)
        on_dev = vrpo_gpu.Learner(dev_cfg, tmp + "/a", dev, resume=False)
        on_cpu = vrpo_gpu.Learner(cfg, tmp + "/b", torch.device("cpu"), resume=False)
        on_cpu.critic.load_state_dict({k: v.cpu() for k, v in on_dev.critic.state_dict().items()})
        d = on_dev.collect()   # sampled on the device
        n = len(d["action"])
        action = torch.from_numpy(d["action"].astype(np.int64))

        def recompute(net, where, order):
            """Log-probabilities of the taken actions, in minibatches of 4096 rows in `order`."""
            out = np.zeros(n, np.float32)
            with torch.no_grad():
                for i in range(0, n, 4096):
                    idx = order[i:i + 4096]
                    x = _unpack(torch.from_numpy(d["feat"][idx]).to(where), native.feature_dim(2))
                    m = _unpack(torch.from_numpy(d["mask"][idx]).to(where), native.NUM_ACTIONS).bool()
                    lp = torch.log_softmax(net(x).masked_fill(~m, -1e9) / cfg.temperature, 1)
                    out[idx] = lp.gather(1, action[idx].to(where)[:, None])[:, 0].float().cpu().numpy()
            return out

        order = np.random.default_rng(0).permutation(n)
        same_device = float(np.abs(recompute(lambda x: on_dev._run(on_dev.actor, x), dev, order) - d["logp"]).max())
        against_cpu = float(np.abs(recompute(qmodel.load(policy, "cpu"), "cpu", order) - d["logp"]).max())
        zero = on_dev.evaluate()["vrpo1_actor_0504"]
        start = [torch.cat([p.detach().cpu().flatten() for p in net.parameters()])
                 for net in (on_dev.actor, on_dev.critic)]
        rows = [learner.update({k: v.copy() for k, v in d.items()}) for learner in (on_dev, on_cpu)]

        def direction(a, b, origin):
            """Cosine of the two updates (parameter change on the device and on the CPU)."""
            da = torch.cat([p.detach().cpu().flatten() for p in a.parameters()]) - origin
            db = torch.cat([p.detach().cpu().flatten() for p in b.parameters()]) - origin
            return float(torch.dot(da, db) / (da.norm() * db.norm() + 1e-30))

        stats = ("critic_loss", "kl", "clip_frac", "adv_std", "mean_abs_delta", "entropy", "critic_mc_mse")
        out = {
            "device": str(dev), "amp": amp, "rows": n,
            "logp_recomputed_on_device_max_abs_diff": same_device,
            "logp_against_cpu_float32_max_abs_diff": against_cpu,
            "self_eval": zero,
            "stats_device_cpu": {k: [rows[0][k], rows[1][k]] for k in stats},
            "update_direction_cosine": {"actor": direction(on_dev.actor, on_cpu.actor, start[0]),
                                        "critic": direction(on_dev.critic, on_cpu.critic, start[1])},
        }
    worst = max(abs(a - b) / (abs(b) + 1e-12) for a, b in out["stats_device_cpu"].values())
    out["stats_max_relative_diff"] = worst
    # Under mixed precision the learner recomputes the behaviour log-probabilities itself, so
    # only gross disagreement is an error there; in float32 the sampler's figures are used as
    # they are and must match closely.
    limits = (2e-3, 5e-2, 0.03) if amp == "off" else (0.5, 0.5, 0.15)
    out["ok"] = bool(same_device < limits[0] and against_cpu < limits[1] and zero == [0.0, 0.0]
                     and worst < limits[2])
    return out


def labels_check(dev: torch.device, amp: str = "off", games: int = 512) -> dict:
    """Counterfactual labels computed with the policy on the device against the same labels with
    the exact CPU forward: the same states, seeds and engine, so every difference comes from the
    forward pass (precision, ties). Greedy play-outs amplify a changed card into a changed label,
    so a few per cent may differ; many more would mean the device plays another policy."""
    from . import labels
    from tuppi_ai.best import EQUITY
    from tuppi_ai.equity import Equity
    device.setup(dev)
    native.set_offer_model(None)
    native.set_branch_share(False)
    table = Equity.load(EQUITY).table

    def env(n):
        e = native.Env(n, 1, table, single_deal=True, encoder=2)
        e.set_sooli(0, False, False, 0.0)
        return e

    cpu_net = qmodel.load(MODELS / "vrpo1_actor_0504.pt", "cpu")
    exact = lockstep.NativeGreedy(native.Mlp(cpu_net))
    on_dev = lockstep.TorchGreedy(qmodel.load(MODELS / "vrpo1_actor_0504.pt", dev), dev, amp=device.AMP[amp])
    d = labels.collect(env(games), exact, games, C.c_uint64(5), p_record=0.08, p_explore=0.01, seed=1)
    seeds = labels.state_seeds(len(d["states"]), 2)
    counts = np.unpackbits(d["mask"], axis=1).sum(1)
    out = {"device": str(dev), "amp": amp, "states": int(len(d["states"]))}
    for name, dd in (("own_play", 0), ("solver_tail", 6)):
        want = labels.branch_labels(env(40000), d["states"], exact, seeds, dd, counts=counts)
        got = labels.branch_labels(env(40000), d["states"], on_dev, seeds, dd, counts=counts)
        valid = want[0] != labels.PAD
        same = (want[1] == got[1])[valid]
        best_w = np.where(valid, want[1].astype(np.float32), -9).argmax(1)
        best_g = np.where(valid, got[1].astype(np.float32), -9).argmax(1)
        out[name] = {"ids_equal": bool(np.array_equal(want[0], got[0])), "labels_identical": float(same.mean()),
                     "best_action_identical": float((best_w == best_g).mean()),
                     "mean_abs_diff": float(np.abs(want[1].astype(np.float32) - got[1].astype(np.float32))[valid].mean())}
    out["ok"] = all(out[k]["ids_equal"] and out[k]["labels_identical"] > 0.95 for k in ("own_play", "solver_tail"))
    return out


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--device", default=None)
    p.add_argument("--games", type=int, default=1024)
    p.add_argument("--amp", default="off", choices=sorted(device.AMP))
    p.add_argument("--labels", action="store_true", help="check the label path instead of the update")
    a = p.parse_args(argv)
    if a.labels:
        result = labels_check(device.pick(a.device), a.amp)
        print(json.dumps(result, indent=1), flush=True)
        if not result["ok"]:
            raise SystemExit("label check failed: the device does not reproduce the CPU's labels")
        return
    result = run(device.pick(a.device), a.games, a.amp)
    print(json.dumps(result, indent=1), flush=True)
    if not result["ok"]:
        raise SystemExit("device check failed: do not train on this device before this is understood")


if __name__ == "__main__":
    main()
