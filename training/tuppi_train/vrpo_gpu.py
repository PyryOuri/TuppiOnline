"""VRPO self-play (ai/tuppi_ai/vrpo.py) for CUDA machines, resumable.

The estimator and the update are those of `tuppi_ai.vrpo` (Fan and Farina's
VRPO: PPO with a privileged Q critic and Q-boosted advantages); its `Critic`,
`trace` and `pack_hidden` are imported, not copied, and tests/test_learner.py
checks that one update here equals one update there. What differs:

- device: CUDA, MPS or CPU; self-play by `lockstep.rollouts` with the actor on
  the device (or `--collector native`: the C rollouts on OpenMP threads);
- it starts from a shipped actor with a new critic, so the actor stays frozen
  until the critic has stopped improving against Monte-Carlo returns of fresh
  rollouts, and then moves in with a reduced learning rate;
- evaluation is rarer, on fixed deals, against a panel of shipped networks, in
  paired duplicate (lockstep.duplicate_eval); a guard stops a run that has
  fallen significantly below its starting network;
- everything needed to continue is saved atomically every few minutes.

    python -m tuppi_train.vrpo_gpu --name run1 --hours 1.5
    python -m tuppi_train.vrpo_gpu --name run1 --hours 1.5          # continues run1
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import numpy as np
import torch
from torch import nn

from . import MODELS, REPO, checkpoint, device, lockstep, tn  # noqa: F401  (tn loads the training library)
from tuppi_ai import model as qmodel
from tuppi_ai import native
from tuppi_ai.value import _unpack
from tuppi_ai.vrpo import HIDDEN_BITS, SCALE, Critic, pack_hidden, trace

PANEL = "vrpo4_final.pt,vrpo3_final.pt,vrpo1_actor_0504.pt"


@dataclass
class Config:
    init: str = str(MODELS / "vrpo4_final.pt")
    panel: str = PANEL               # evaluation opponents (files in ai/models or paths); the first is the parent
    offer_model: str = ""            # fast sooli-offer model (offer.py); "" = the exact heuristic
    critic_init: str = ""            # a critic checkpoint of the same shape; "" = a new critic
    ruleset: int = 3
    games_per_iter: int = 16384
    temperature: float = 1.0
    lam: float = 0.95
    clip: float = 0.2
    ent_coef: float = 0.001
    actor_epochs: int = 4
    critic_epochs: int = 4
    minibatch: int = 16384
    lr_actor: float = 3e-5
    lr_critic: float = 3e-4
    critic_width: int = 512
    critic_blocks: int = 4
    max_kl: float = 0.02             # stop the actor epochs early above this mean KL
    # Critic warm-up: the actor is frozen for at least warmup_min iterations and until the critic's
    # error against Monte-Carlo returns of fresh rollouts has improved by less than warmup_tol
    # (relative) over warmup_patience iterations; at the latest after warmup_max.
    warmup_min: int = 8
    warmup_max: int = 80
    warmup_patience: int = 5
    warmup_tol: float = 0.01
    actor_ramp: int = 30             # iterations over which the actor's rate rises from a third to lr_actor
    collector: str = "lockstep"      # or "native"
    eval_every: int = 25
    eval_base: int = 2048
    eval_seed: int = 20261125
    stop_patience: int = 3           # evaluations significantly below the parent before the run stops; 0 = never
    save_minutes: float = 5.0
    milestone_every: int = 100
    keep_milestones: int = 40
    seed: int = 1
    compile: bool = False
    tf32: bool = True                # CUDA only (device.setup)


def resolve_model(name: str) -> Path:
    path = Path(name)
    return path if path.exists() else MODELS / name


class Learner:
    def __init__(self, cfg: Config, out: Path, dev: torch.device | None = None, resume: bool = True):
        self.cfg, self.out = cfg, Path(out)
        self.dev = dev or device.pick()
        device.setup(self.dev, cfg.tf32)
        torch.manual_seed(cfg.seed)
        self.actor = qmodel.load(cfg.init, self.dev).train()
        self.encoder, self.dim = self.actor.encoder, native.feature_dim(self.actor.encoder)
        self.critic = Critic(self.dim + HIDDEN_BITS, cfg.critic_width, cfg.critic_blocks).to(self.dev)
        if cfg.critic_init:
            ck = torch.load(cfg.critic_init, map_location="cpu")
            if ck["config"] != self.critic.config:
                raise ValueError(f"critic shape {ck['config']} != {self.critic.config}")
            self.critic.load_state_dict(ck["state"])
        self.opt_a = device.adamw(self.actor.parameters(), cfg.lr_actor, 0.0, self.dev)
        self.opt_c = device.adamw(self.critic.parameters(), cfg.lr_critic, 1e-5, self.dev)
        self.a_fwd = torch.compile(self.actor) if cfg.compile else self.actor
        self.c_fwd = torch.compile(self.critic) if cfg.compile else self.critic
        if cfg.offer_model:
            from tuppi_ai.offer_screen import load as load_offer
            om, _ = load_offer(cfg.offer_model)
            self._offer = native.Mlp(om, in_dim=om.config["in_dim"], out_dim=1)
            native.set_offer_model(self._offer)
        else:
            native.set_offer_model(None)
        from tuppi_ai.best import EQUITY
        from tuppi_ai.equity import Equity
        table = Equity.load(EQUITY).table
        self.env = native.Env(cfg.games_per_iter, cfg.seed, table, single_deal=True, encoder=self.encoder)
        self.env_eval = native.Env(8 * cfg.eval_base, cfg.seed + 2, table, single_deal=True, encoder=self.encoder)
        for env in (self.env, self.env_eval):
            env.set_sooli(0, False, False, 0.0)
        if cfg.collector == "native":
            self.env.set_incremental(True, self.actor.config["width"])
            native.set_rollout_chunk(128)
        self.panel = []
        for name in filter(None, cfg.panel.split(",")):
            net = qmodel.load(resolve_model(name.strip()), self.dev)
            if net.encoder != self.encoder:
                raise ValueError(f"{name}: encoder {net.encoder} != {self.encoder}")
            self.panel.append((Path(name.strip()).stem, net))
        self.rng = C.c_uint64(cfg.seed * 0x9E3779B97F4A7C15 % 2**64 + 11)
        self.gen = device.generator(self.dev, cfg.seed + 101)
        self.iteration = 0
        self.warm = cfg.warmup_max > 0      # the actor is still frozen
        self.actor_iters = 0                # iterations in which the actor was updated
        self.mc_hist: list[float] = []      # critic error against Monte-Carlo returns, per iteration
        self.below = 0                      # consecutive evaluations significantly below the parent
        self.best = {"mean": None, "iteration": None}
        self.stopped = ""
        self.seconds = 0.0                  # training time over all sessions
        self.store = checkpoint.Rotating(self.out / "ckpt")
        self._last_save = time.time()
        if resume:
            self._restore()

    # ------------------------------------------------------------- self-play
    def _actor_cpu(self) -> qmodel.QNet:
        net = qmodel.QNet(**self.actor.config)
        net.load_state_dict({k: v.detach().cpu() for k, v in self.actor.state_dict().items()})
        return net.eval()

    def collect(self, timing: dict | None = None) -> dict:
        """One batch of on-policy deals: the dict of `native.ppo_rollouts`."""
        cfg = self.cfg
        if cfg.collector == "native":
            return native.ppo_rollouts(self.env, native.Mlp(self._actor_cpu()), cfg.games_per_iter, cfg.ruleset,
                                       self.rng, cfg.temperature)
        sampler = lockstep.TorchSampler(self.actor, self.dev, cfg.temperature, self.gen, self.encoder)
        return lockstep.rollouts(self.env, sampler, cfg.games_per_iter, cfg.ruleset, self.rng, self.encoder,
                                 timing=timing)

    def _logits(self, x, mask):
        return self.a_fwd(x).masked_fill(~mask, -1e9) / self.cfg.temperature

    # ---------------------------------------------------------------- update
    def update(self, d: dict) -> dict:
        """The update of `tuppi_ai.vrpo.VRPO.iterate` on one batch of rollouts."""
        cfg, dev = self.cfg, self.dev
        n = len(d["action"])
        if n >= cfg.games_per_iter * 64:
            raise RuntimeError("trajectory buffer full; deals would be truncated")
        feat = torch.from_numpy(d["feat"]).to(dev)
        hid = torch.from_numpy(pack_hidden(d["hidden"])).to(dev)
        maskp = torch.from_numpy(d["mask"]).to(dev)
        action = torch.from_numpy(d["action"].astype(np.int64)).to(dev)
        logp_b = torch.from_numpy(d["logp"]).to(dev)
        team = torch.from_numpy(d["team"].astype(np.int64)).to(dev)
        deal = torch.from_numpy(d["deal"].astype(np.int64)).to(dev)
        reward = torch.from_numpy(d["reward"]).to(dev) * SCALE
        T = int(d["step"].max()) + 1
        index = torch.full((cfg.games_per_iter, T), -1, dtype=torch.long, device=dev)
        index[deal, torch.from_numpy(d["step"].astype(np.int64)).to(dev)] = torch.arange(n, device=dev)

        def batch(idx):
            x = _unpack(feat[idx], self.dim)
            xc = torch.cat([x, _unpack(hid[idx], HIDDEN_BITS)], 1)
            m = _unpack(maskp[idx], native.NUM_ACTIONS).bool()
            return x, xc, m

        # advantages and critic targets from the current critic and actor (fixed for this batch)
        with torch.no_grad():
            qa, v = torch.zeros(n, device=dev), torch.zeros(n, device=dev)
            ent_sum = 0.0
            for i in range(0, n, 65536):
                sl = torch.arange(i, min(i + 65536, n), device=dev)
                x, xc, m = batch(sl)
                q = self.critic(xc)
                pi = torch.softmax(self.actor(x).masked_fill(~m, -1e9) / cfg.temperature, 1)
                qa[sl] = q.gather(1, action[sl, None])[:, 0]
                v[sl] = (pi * q.masked_fill(~m, 0.0)).sum(1)
                ent_sum += float(-(pi * torch.log(pi.clamp(min=1e-12))).sum())
            G, delta = trace(qa, v, team, reward, index, cfg.lam)
            q_target = qa + G
            adv = qa - v + G
            ev = float(1.0 - (q_target - qa).var() / q_target.var().clamp(min=1e-12))
            choice = torch.zeros(n, dtype=torch.bool, device=dev)
            for i in range(0, n, 65536):
                sl = torch.arange(i, min(i + 65536, n), device=dev)
                choice[sl] = _unpack(maskp[sl], native.NUM_ACTIONS).sum(1) > 1
            # The critic against the deal's actual outcome from the actor's side: rollouts the
            # critic has not been trained on, and a target that does not involve the critic.
            mc = torch.where(team == 0, reward[deal], -reward[deal])
            mc_mse = float(((qa - mc) ** 2).mean()) / SCALE ** 2
            mc_ev = float(1.0 - ((qa - mc) ** 2).mean() / mc.var().clamp(min=1e-12))
        train_actor = self._warmup_step(mc_mse)
        # critic
        closs = []
        for _ in range(cfg.critic_epochs):
            perm = torch.randperm(n, device=dev)
            for i in range(0, n, cfg.minibatch):
                idx = perm[i:i + cfg.minibatch]
                _, xc, _ = batch(idx)
                pred = self.c_fwd(xc).gather(1, action[idx, None])[:, 0]
                loss = 0.5 * ((pred - q_target[idx]) ** 2).mean()
                self.opt_c.zero_grad(set_to_none=True)
                loss.backward()
                nn.utils.clip_grad_norm_(self.critic.parameters(), 1.0)
                self.opt_c.step()
                closs.append(float(loss.detach()))
        # actor (after the critic warm-up)
        stats = {"kl": None, "clip_frac": None, "epochs": 0, "lr_actor": None}
        if train_actor:
            lr = cfg.lr_actor * (1.0 if cfg.actor_ramp <= 0 else
                                 (1.0 + 2.0 * min(1.0, self.actor_iters / cfg.actor_ramp)) / 3.0)
            for group in self.opt_a.param_groups:
                group["lr"] = lr
            a_norm = (adv - adv[choice].mean()) / (adv[choice].std() + 1e-8)
            for epoch in range(cfg.actor_epochs):
                perm = torch.randperm(n, device=dev)
                kls, clips = [], []
                for i in range(0, n, cfg.minibatch):
                    idx = perm[i:i + cfg.minibatch]
                    x, _, m = batch(idx)
                    logits = self._logits(x, m)
                    logp_all = torch.log_softmax(logits, 1)
                    logp = logp_all.gather(1, action[idx, None])[:, 0]
                    ratio = torch.exp(logp - logp_b[idx])
                    a = a_norm[idx]
                    pg = -torch.min(ratio * a, ratio.clamp(1 - cfg.clip, 1 + cfg.clip) * a).mean()
                    p = torch.exp(logp_all)
                    ent = -(p * logp_all.masked_fill(~m, 0.0)).sum(1).mean()
                    loss = pg - cfg.ent_coef * ent
                    self.opt_a.zero_grad(set_to_none=True)
                    loss.backward()
                    nn.utils.clip_grad_norm_(self.actor.parameters(), 1.0)
                    self.opt_a.step()
                    kls.append(float((logp_b[idx] - logp).mean().detach()))
                    clips.append(float(((ratio - 1).abs() > cfg.clip).float().mean().detach()))
                stats = {"kl": float(np.mean(kls)), "clip_frac": float(np.mean(clips)), "epochs": epoch + 1,
                         "lr_actor": lr}
                if stats["kl"] > cfg.max_kl:
                    break
            self.actor_iters += 1
        self.iteration += 1
        return {"iteration": self.iteration, "rows": n, "deals": cfg.games_per_iter,
                "critic_loss": float(np.mean(closs[-10:])) / SCALE ** 2,
                "mean_abs_delta": float(delta.abs().mean()) / SCALE, "adv_std": float(adv.std()) / SCALE,
                "critic_ev": ev, "critic_mc_mse": mc_mse, "critic_mc_ev": mc_ev,
                "choice_share": float(choice.float().mean()), "entropy": ent_sum / n, "warmup": self.warm, **stats}

    def _warmup_step(self, mc_mse: float) -> bool:
        """Records the critic's error on this batch; True if the actor trains in this iteration."""
        cfg = self.cfg
        self.mc_hist.append(mc_mse)
        if self.warm:
            k, p = len(self.mc_hist) - 1, cfg.warmup_patience  # k = iterations the critic has trained
            if k >= cfg.warmup_max:
                self.warm = False
            elif k >= max(cfg.warmup_min, p + 1):
                before, recent = min(self.mc_hist[:-p]), min(self.mc_hist[-p:])
                if recent > (1.0 - cfg.warmup_tol) * before:
                    self.warm = False
        return not self.warm

    # ------------------------------------------------------------ evaluation
    def evaluate(self, base: int | None = None, seed: int | None = None, sampled: float = 0.0) -> dict:
        """Paired duplicate of the actor against every panel network: name -> [mean, 95% half-width]
        of the actor pair's match-equity change per deal. The same seed gives the same deals."""
        cfg = self.cfg
        base = base or cfg.eval_base
        env = self.env_eval if 8 * base <= self.env_eval.n else self._env(8 * base)

        def chooser(net):
            if sampled > 0:
                return lockstep.TorchSampler(net, self.dev, sampled, device.generator(self.dev, 7), self.encoder)
            return lockstep.TorchGreedy(net, self.dev, self.encoder)

        out = {}
        for name, net in self.panel:
            vals = lockstep.duplicate_eval(env, chooser(self.actor), chooser(net), base, cfg.ruleset,
                                           C.c_uint64(seed if seed is not None else cfg.eval_seed), self.encoder)
            out[name] = lockstep.interval(vals)
        return out

    def _env(self, n: int) -> "native.Env":
        from tuppi_ai.best import EQUITY
        from tuppi_ai.equity import Equity
        env = native.Env(n, self.cfg.seed + 3, Equity.load(EQUITY).table, single_deal=True, encoder=self.encoder)
        env.set_sooli(0, False, False, 0.0)
        return env

    def _judge(self, row: dict) -> None:
        """Evaluation, the best-so-far actor and the stop rule (all against the parent, panel[0])."""
        cfg = self.cfg
        result = self.evaluate()
        row["eval"] = result
        if not self.panel:
            return
        mean, half = result[self.panel[0][0]]
        if self.best["mean"] is None or mean > self.best["mean"]:
            self.best = {"mean": mean, "iteration": self.iteration}
            qmodel.save(self._actor_cpu(), self.out / "best_actor.pt", iteration=self.iteration, eval=result)
        self.below = self.below + 1 if mean + half < 0 else 0
        if cfg.stop_patience and self.below >= cfg.stop_patience:
            self.stopped = (f"guard: {self.below} evaluations significantly below {self.panel[0][0]} "
                            f"(last {mean:+.5f} +/- {half:.5f}); best_actor.pt is iteration {self.best['iteration']}")
            row["stopped"] = self.stopped

    # ------------------------------------------------------------ iteration
    def iterate(self) -> dict:
        cfg = self.cfg
        t0 = time.perf_counter()
        timing: dict = {}
        d = self.collect(timing)
        t_roll = time.perf_counter() - t0
        row = self.update(d)
        row["rollout_s"] = round(t_roll, 2)
        if timing:
            row["rollout_split"] = {k: round(float(timing[k]), 2) for k in ("choose", "sooli", "encode")}
        row["update_s"] = round(time.perf_counter() - t0 - t_roll, 2)
        if not self.warm and (self.actor_iters == 1 or self.iteration % cfg.eval_every == 0):
            self._judge(row)
        if cfg.milestone_every and self.iteration % cfg.milestone_every == 0 and not self.warm:
            self._milestone()
        row["total_s"] = round(time.perf_counter() - t0, 2)
        self.seconds += time.perf_counter() - t0
        row["hours"] = round(self.seconds / 3600, 3)
        self.out.mkdir(parents=True, exist_ok=True)
        with open(self.out / "log.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        if time.time() - self._last_save >= cfg.save_minutes * 60:
            self.save()
        return row

    def _milestone(self) -> None:
        folder = self.out / "actors"
        folder.mkdir(parents=True, exist_ok=True)
        qmodel.save(self._actor_cpu(), folder / f"actor_{self.iteration:06d}.pt", iteration=self.iteration)
        files = sorted(folder.glob("actor_*.pt"))
        for old in files[:max(0, len(files) - self.cfg.keep_milestones)]:
            old.unlink()

    # ---------------------------------------------------------------- resume
    def state(self) -> dict:
        cpu = lambda sd: {k: v.detach().cpu() for k, v in sd.items()}  # noqa: E731
        return {
            "config": asdict(self.cfg), "iteration": self.iteration,
            "actor_config": self.actor.config, "actor": cpu(self.actor.state_dict()),
            "critic_config": self.critic.config, "critic": cpu(self.critic.state_dict()),
            "opt_a": self.opt_a.state_dict(), "opt_c": self.opt_c.state_dict(),
            "rng": int(self.rng.value), "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all() if self.dev.type == "cuda" else None,
            "gen": self.gen.get_state() if self.gen is not None else None,
            "warm": self.warm, "actor_iters": self.actor_iters, "mc_hist": list(self.mc_hist),
            "below": self.below, "best": dict(self.best), "stopped": self.stopped, "seconds": self.seconds,
        }

    def save(self) -> Path:
        path = self.store.save(self.state())
        self._last_save = time.time()
        return path

    def _restore(self) -> bool:
        s = self.store.load()
        if s is None:
            return False
        if s["actor_config"] != self.actor.config or s["critic_config"] != self.critic.config:
            raise ValueError("the checkpoint's network shapes differ from this configuration")
        self.actor.load_state_dict(s["actor"])
        self.critic.load_state_dict(s["critic"])
        self.opt_a.load_state_dict(s["opt_a"])
        self.opt_c.load_state_dict(s["opt_c"])
        self.rng = C.c_uint64(s["rng"])
        torch.set_rng_state(s["torch_rng"])
        if self.dev.type == "cuda" and s.get("cuda_rng") is not None:
            torch.cuda.set_rng_state_all(s["cuda_rng"])
        if self.gen is not None and s.get("gen") is not None:
            self.gen.set_state(s["gen"])
        self.iteration, self.warm, self.actor_iters = s["iteration"], s["warm"], s["actor_iters"]
        self.mc_hist, self.below, self.best = list(s["mc_hist"]), s["below"], dict(s["best"])
        self.stopped, self.seconds = s["stopped"], s["seconds"]
        log = self.out / "log.jsonl"
        if log.exists():  # drop the rows of iterations that were lost with the session
            rows = [line for line in log.read_text().splitlines()
                    if line.strip() and json.loads(line)["iteration"] <= self.iteration]
            log.write_text("".join(r + "\n" for r in rows))
        return True


def brief(row: dict) -> str:
    """One short line per iteration for a notebook; log.jsonl has the full row."""
    parts = [f"{row['iteration']:6d}", f"{row['total_s']:6.1f}s (play {row['rollout_s']:.1f}, learn {row['update_s']:.1f})",
             f"critic fit {row['critic_mc_ev']:.3f}"]
    parts.append("actor frozen" if row["epochs"] == 0 else f"kl {row['kl']:.4f} x{row['epochs']}")
    parts.append(f"entropy {row['entropy']:.4f}")
    if "eval" in row:
        parts.append("EVAL " + ", ".join(f"{k} {v[0]:+.5f}+/-{v[1]:.5f}" for k, v in row["eval"].items()))
    if "stopped" in row:
        parts.append("STOPPED " + row["stopped"])
    return " | ".join(parts)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--name", required=True)
    p.add_argument("--print", dest="show", choices=("brief", "json"), default="brief")
    p.add_argument("--print-every", type=int, default=1, help="brief lines: every Nth iteration (evaluations always)")
    p.add_argument("--out", type=Path, default=None, help="run directory (default training/runs/<name>)")
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--iterations", type=int, default=10**9)
    p.add_argument("--device", default=None)
    for f in fields(Config):
        kind = type(f.default)
        p.add_argument("--" + f.name.replace("_", "-"), default=None,
                       type=(lambda s: s.lower() in ("1", "true")) if kind is bool else kind)
    a = p.parse_args(argv)
    out = a.out or REPO / "training" / "runs" / a.name
    given = {f.name: getattr(a, f.name) for f in fields(Config) if getattr(a, f.name) is not None}
    saved = checkpoint.Rotating(out / "ckpt").load()
    base = saved["config"] if saved else {}
    cfg = Config(**{**{k: v for k, v in base.items() if k in {f.name for f in fields(Config)}}, **given})
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=1))
    dev = device.pick(a.device)
    print(json.dumps({"run": a.name, "out": str(out), "resumed_from": saved["iteration"] if saved else None,
                      "threads": tn.threads(), **device.describe(dev)}), flush=True)
    learner = Learner(cfg, out, dev)
    t_end = time.time() + 3600 * a.hours
    while time.time() < t_end and learner.iteration < a.iterations and not learner.stopped:
        row = learner.iterate()
        if a.show == "json":
            print(json.dumps(row), flush=True)
        elif "eval" in row or "stopped" in row or row["iteration"] % a.print_every == 0:
            print(brief(row), flush=True)
    learner.save()
    print(json.dumps({"finished": learner.stopped or "time or iteration limit", "iteration": learner.iteration,
                      "hours": round(learner.seconds / 3600, 3), "best": learner.best}), flush=True)


if __name__ == "__main__":
    main()
