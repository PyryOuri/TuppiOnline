"""VRPO self-play for Tuppi: PPO with a privileged Q critic and Q-boosted advantages.

Fan and Farina, "GAE Falls Short in Imperfect-Information Self-Play
Reinforcement Learning" (arXiv 2605.19235, May 2026). Their estimator, with a
centralised critic Q(s, a) and V(s) = sum_a pi(a|o) Q(s, a):

    delta_t = r_t + gamma * V(s_{t+1}) - Q(s_t, a_t)
    Q_target_t = Q(s_t, a_t) + sum_{t' >= t} (lambda gamma)^(t'-t) delta_t'
    A_boost_t = Q(s_t, a_t) - V(s_t) + sum_{t' >= t} (lambda gamma)^(t'-t) delta_t'

The actor takes PPO clipped steps on A_boost; the critic regresses Q(s_t, a_t)
on Q_target_t. lambda = 0.95, gamma = 1, 4 actor and 4 critic epochs per
batch, as in the paper.

For Tuppi:
- An episode is one deal; the only reward is the deal's match-equity change
  at the end.
- Values are kept from the acting team's side, so every term from a later
  step taken by the other team changes sign.
- The critic sees the actor's observation plus the three hidden hands (the
  full state); it is used only in training.
- The actor is observation-only and deploys through the ordinary native
  network path.
- Sooli phases are played by the heuristics inside the environment.

    python -m tuppi_ai.vrpo --name vrpo1 --hours 4
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from . import model as qmodel
from . import native
from .model import ResBlock
from .value import _unpack

ROOT = Path(__file__).resolve().parents[1]
SCALE = qmodel.RETURN_SCALE
HIDDEN_BITS = 156  # three 52-card hands, relative seats 1..3


@dataclass
class Config:
    init: str = str(ROOT / "models" / "sp1_policy_043.pt")
    baseline: str = str(ROOT.parent / "TuppiAI" / "runs" / "bc_small.pt")
    reference: str = str(ROOT / "models" / "sp1_policy_043.pt")
    offer_model: str = str(ROOT / "models" / "offer_model_selfplay.pt")
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
    critic_init: str = ""            # warm start: a critic_latest.pt of an earlier run (same shape)
    warmup_iters: int = 6            # critic-only iterations before the actor moves
    max_kl: float = 0.02             # stop the actor epochs early above this mean KL
    eval_every: int = 3
    eval_base: int = 8192
    final_eval_base: int = 0        # 0: use eval_base; final evaluation is never skipped
    isolate_eval_rng: bool = False # opt-in; historical runs used the rollout RNG for checks too
    seed: int = 1
    torch_seed: int = -1           # -1 retains historical unseeded Torch initialisation
    compile: bool = True

    def __post_init__(self):
        if self.eval_every < 0 or self.eval_base < 2 or self.final_eval_base < 0:
            raise ValueError("eval_every must be >= 0; evaluation sizes must be >= 2 (final 0 inherits)")
        if self.final_eval_base == 1:
            raise ValueError("final_eval_base must be 0 or >= 2")
        if min(self.games_per_iter, self.minibatch, self.actor_epochs, self.critic_epochs) < 1:
            raise ValueError("batch sizes and update epoch counts must be positive")


def _host_stats(values: list[torch.Tensor]) -> np.ndarray:
    """One device-to-host read per group, with the old float64 host reduction."""
    return torch.stack(values).detach().cpu().numpy().astype(np.float64)


class Critic(nn.Module):
    def __init__(self, in_dim: int, width: int, blocks: int):
        super().__init__()
        self.config = {"in_dim": in_dim, "width": width, "blocks": blocks}
        self.inp = nn.Linear(in_dim, width)
        self.blocks = nn.Sequential(*[ResBlock(width) for _ in range(blocks)])
        self.norm = nn.LayerNorm(width)
        self.out = nn.Linear(width, native.NUM_ACTIONS)
        with torch.no_grad():
            self.out.weight.zero_()
            self.out.bias.zero_()

    def forward(self, x):
        return self.out(torch.relu(self.norm(self.blocks(torch.relu(self.inp(x.float()))))))


def pack_hidden(hidden: np.ndarray) -> np.ndarray:
    """uint64 [n, 3] hands -> packed bits [n, 20] (156 bits: 3 x 52, relative seats 1..3)."""
    bits = ((hidden[:, :, None] >> np.arange(52, dtype=np.uint64)) & np.uint64(1)).astype(np.uint8)
    return np.packbits(bits.reshape(len(hidden), HIDDEN_BITS), axis=1)


def trace(qa: torch.Tensor, v: torch.Tensor, team: torch.Tensor, reward_team0: torch.Tensor, index: torch.Tensor,
          lam: float) -> tuple[torch.Tensor, torch.Tensor]:
    """Expected SARSA(lambda) residual sums G_t, and the terminal-aware next values, for trajectories
    laid out as index[deal, step] (-1 = padding). Values are from the acting team's side.
    Returns (G per row, delta per row)."""
    D, T = index.shape
    valid = index >= 0
    safe = index.clamp(min=0)
    qa_m, v_m, team_m = qa[safe], v[safe], team[safe]
    last = valid & ~torch.cat([valid[:, 1:], torch.zeros(D, 1, dtype=torch.bool, device=index.device)], 1)
    side = torch.where(team_m == 0, 1.0, -1.0)
    # next step's value, from this step's side (sign flips when the other team acts next)
    v_next = torch.cat([v_m[:, 1:], torch.zeros(D, 1, device=v.device)], 1)
    same = torch.cat([team_m[:, 1:] == team_m[:, :-1], torch.ones(D, 1, dtype=torch.bool, device=v.device)], 1)
    flip = torch.where(same, 1.0, -1.0)
    r = torch.where(last, reward_team0[:, None] * side, torch.zeros_like(v_m))
    delta = r + torch.where(last, torch.zeros_like(v_m), flip * v_next) - qa_m
    delta = torch.where(valid, delta, torch.zeros_like(delta))
    G = torch.zeros_like(delta)
    run = torch.zeros(D, device=v.device)
    for t in range(T - 1, -1, -1):
        cont = torch.where(last[:, t] | ~valid[:, t], torch.zeros_like(run), flip[:, t] * run)
        run = delta[:, t] + lam * cont
        G[:, t] = run
    out_G = torch.zeros_like(qa)
    out_d = torch.zeros_like(qa)
    out_G[index[valid]] = G[valid]
    out_d[index[valid]] = delta[valid]
    return out_G, out_d


class VRPO:
    def __init__(self, cfg: Config, out: Path):
        self.cfg, self.out = cfg, out
        if cfg.torch_seed >= 0:
            torch.manual_seed(cfg.torch_seed)
        self.dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
        self.actor = qmodel.load(cfg.init, self.dev).train()
        self.encoder, self.dim = self.actor.encoder, native.feature_dim(self.actor.encoder)
        self.critic = Critic(self.dim + HIDDEN_BITS, cfg.critic_width, cfg.critic_blocks).to(self.dev)
        if cfg.critic_init:
            ck = torch.load(cfg.critic_init, map_location="cpu")
            if ck["config"] != self.critic.config:
                raise ValueError(f"critic shape {ck['config']} != {self.critic.config}")
            self.critic.load_state_dict(ck["state"])
        self.opt_a = torch.optim.AdamW(self.actor.parameters(), lr=cfg.lr_actor, weight_decay=0.0,
                                       fused=self.dev.type == "mps")
        self.opt_c = torch.optim.AdamW(self.critic.parameters(), lr=cfg.lr_critic, weight_decay=1e-5,
                                       fused=self.dev.type == "mps")
        self.a_fwd = torch.compile(self.actor) if cfg.compile else self.actor
        self.c_fwd = torch.compile(self.critic) if cfg.compile else self.critic
        if cfg.offer_model:
            from .offer_screen import load as load_offer
            om, _ = load_offer(cfg.offer_model)
            self._offer = native.Mlp(om, in_dim=om.config["in_dim"], out_dim=1)
            native.set_offer_model(self._offer)
        from .best import EQUITY
        from .equity import Equity
        table = Equity.load(EQUITY).table
        self.equity_table = table
        self.env = native.Env(cfg.games_per_iter, cfg.seed, table, single_deal=True, encoder=self.encoder)
        self.env_eval = native.Env(8 * cfg.eval_base, cfg.seed + 2, table, single_deal=True, encoder=self.encoder)
        for env in (self.env, self.env_eval):
            env.set_sooli(0, False, False, 0.0)
        self.env.set_incremental(True, self.actor.config["width"])
        self.baseline = native.Mlp(qmodel.load(cfg.baseline, "cpu"))
        self.reference = native.Mlp(qmodel.load(cfg.reference, "cpu"))
        self.rng = C.c_uint64(cfg.seed * 0x9E3779B97F4A7C15 % 2**64 + 11)
        self.eval_rng = (C.c_uint64((cfg.seed ^ 0xD1B54A32D192ED03) % 2**64)
                         if cfg.isolate_eval_rng else self.rng)
        self.iteration = 0
        self._last_check = None

    def _actor_cpu(self) -> qmodel.QNet:
        if self.cfg.isolate_eval_rng:
            # Exporting a snapshot initialises then overwrites CPU weights.
            # Monitoring cadence must not advance the CPU training RNG.
            with torch.random.fork_rng(devices=[]):
                net = qmodel.QNet(**self.actor.config)
        else:
            net = qmodel.QNet(**self.actor.config)
        net.load_state_dict({k: v.detach().cpu() for k, v in self.actor.state_dict().items()})
        return net.eval()

    def _logits(self, x, mask):
        return self.a_fwd(x).masked_fill(~mask, -1e9) / self.cfg.temperature

    def iterate(self) -> dict:
        cfg = self.cfg
        t0 = time.perf_counter()
        mlp = native.Mlp(self._actor_cpu())
        d = native.ppo_rollouts(self.env, mlp, cfg.games_per_iter, cfg.ruleset, self.rng, cfg.temperature)
        n = len(d["action"])
        if n >= cfg.games_per_iter * 64:
            raise RuntimeError("trajectory buffer full; deals would be truncated")
        t_roll = time.perf_counter() - t0
        dev = self.dev
        feat = torch.from_numpy(d["feat"]).to(dev)
        hid = torch.from_numpy(pack_hidden(d["hidden"])).to(dev)
        maskp = torch.from_numpy(d["mask"]).to(dev)
        action = torch.from_numpy(d["action"].astype(np.int64)).to(dev)
        logp_b = torch.from_numpy(d["logp"]).to(dev)
        team = torch.from_numpy(d["team"].astype(np.int64)).to(dev)
        reward = torch.from_numpy(d["reward"]).to(dev) * SCALE
        # trajectories: index[deal, step] -> row
        T = int(d["step"].max()) + 1
        index = torch.full((cfg.games_per_iter, T), -1, dtype=torch.long, device=dev)
        index[torch.from_numpy(d["deal"].astype(np.int64)).to(dev), torch.from_numpy(d["step"].astype(np.int64)).to(dev)] = \
            torch.arange(n, device=dev)

        def actor_batch(idx):
            x = _unpack(feat[idx], self.dim)
            m = _unpack(maskp[idx], native.NUM_ACTIONS).bool()
            return x, m

        def critic_batch(idx, x=None):
            if x is None:
                x = _unpack(feat[idx], self.dim)
            xc = torch.cat([x, _unpack(hid[idx], HIDDEN_BITS)], 1)
            return xc

        # advantages and critic targets from the current critic and actor (fixed for this batch)
        with torch.no_grad():
            qa, v = torch.zeros(n, device=dev), torch.zeros(n, device=dev)
            ent_sums = []
            for i in range(0, n, 65536):
                sl = torch.arange(i, min(i + 65536, n), device=dev)
                x, m = actor_batch(sl)
                xc = critic_batch(sl, x)
                q = self.critic(xc)
                pi = torch.softmax(self.actor(x).masked_fill(~m, -1e9) / cfg.temperature, 1)
                qa[sl] = q.gather(1, action[sl, None])[:, 0]
                v[sl] = (pi * q.masked_fill(~m, 0.0)).sum(1)
                ent_sums.append(-(pi * torch.log(pi.clamp(min=1e-12))).sum().detach())
            G, delta = trace(qa, v, team, reward, index, cfg.lam)
            q_target = qa + G
            adv = qa - v + G
            # share of the target variance the pre-update critic already explains
            ev = float(1.0 - (q_target - qa).var() / q_target.var().clamp(min=1e-12))
            choice = torch.zeros(n, dtype=torch.bool, device=dev)  # decisions with more than one legal action
            for i in range(0, n, 65536):
                sl = torch.arange(i, min(i + 65536, n), device=dev)
                choice[sl] = _unpack(maskp[sl], native.NUM_ACTIONS).sum(1) > 1
        # critic
        closs = []
        for _ in range(cfg.critic_epochs):
            perm = torch.randperm(n, device=dev)
            for i in range(0, n, cfg.minibatch):
                idx = perm[i:i + cfg.minibatch]
                xc = critic_batch(idx)
                pred = self.c_fwd(xc).gather(1, action[idx, None])[:, 0]
                loss = 0.5 * ((pred - q_target[idx]) ** 2).mean()
                self.opt_c.zero_grad(set_to_none=True)
                loss.backward()
                nn.utils.clip_grad_norm_(self.critic.parameters(), 1.0)
                self.opt_c.step()
                closs.append(loss.detach())
        # actor (after the critic warm-up)
        stats = {"kl": None, "clip_frac": None, "epochs": 0}
        if self.iteration >= cfg.warmup_iters:
            a_norm = (adv - adv[choice].mean()) / (adv[choice].std() + 1e-8)
            for epoch in range(cfg.actor_epochs):
                perm = torch.randperm(n, device=dev)
                kls, clips = [], []
                for i in range(0, n, cfg.minibatch):
                    idx = perm[i:i + cfg.minibatch]
                    x, m = actor_batch(idx)
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
                    kls.append((logp_b[idx] - logp).mean().detach())
                    clips.append(((ratio - 1).abs() > cfg.clip).float().mean().detach())
                stats = {"kl": float(_host_stats(kls).mean()), "clip_frac": float(_host_stats(clips).mean()),
                         "epochs": epoch + 1}
                if stats["kl"] > cfg.max_kl:
                    break
        self.iteration += 1
        row = {"iteration": self.iteration, "rows": n, "deals": cfg.games_per_iter,
               "critic_loss": float(_host_stats(closs[-10:]).mean()) / SCALE ** 2,
               "mean_abs_delta": float(delta.abs().mean()) / SCALE, "adv_std": float(adv.std()) / SCALE,
               "critic_ev": ev, "choice_share": float(choice.float().mean()),
               "entropy": float(_host_stats(ent_sums).sum()) / n, **stats, "rollout_s": round(t_roll, 1)}
        row["training_s"] = round(time.perf_counter() - t0, 1)
        e0 = time.perf_counter()
        if cfg.eval_every and self.iteration % cfg.eval_every == 0:
            row.update(self._evaluate_and_save(cfg.eval_base))
        row["evaluation_s"] = round(time.perf_counter() - e0, 1)
        row["total_s"] = round(time.perf_counter() - t0, 1)
        with open(self.out / "log.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def _evaluate_and_save(self, base: int) -> dict:
        """Frozen-actor native monitoring; not the authoritative strength endpoint."""
        env = self.env_eval
        if base != self.cfg.eval_base:
            env = native.Env(8 * base, self.cfg.seed + 2, self.equity_table,
                             single_deal=True, encoder=self.encoder)
            env.set_sooli(0, False, False, 0.0)
        nxt = native.Mlp(self._actor_cpu())
        metrics = {}
        for name, other in (("vs_ref", self.reference), ("vs_clone", self.baseline)):
            vals = native.duplicate_eval(env, nxt, other, base, self.cfg.ruleset, self.eval_rng)
            metrics[name] = [float(vals.mean()), float(1.96 * vals.std(ddof=1) / np.sqrt(len(vals)))]
        vals = native.duplicate_eval(env, nxt, self.reference, base, self.cfg.ruleset, self.eval_rng,
                                     temperature=self.cfg.temperature)
        metrics["vs_ref_sampled"] = [float(vals.mean()), float(1.96 * vals.std(ddof=1) / np.sqrt(len(vals)))]
        qmodel.save(self._actor_cpu(), self.out / f"actor_{self.iteration:04d}.pt")
        torch.save({"config": self.critic.config, "state": {k: v.cpu() for k, v in self.critic.state_dict().items()}},
                   self.out / "critic_latest.pt")
        self._last_check = (self.iteration, base, metrics)
        return metrics

    def finalize(self) -> dict:
        """Always check/save the actual final actor, even between periodic checks."""
        if self.iteration == 0:
            raise RuntimeError("cannot finalize a run with no training iterations")
        t0 = time.perf_counter()
        base = self.cfg.final_eval_base or self.cfg.eval_base
        reused = self._last_check is not None and self._last_check[:2] == (self.iteration, base)
        metrics = self._last_check[2] if reused else self._evaluate_and_save(base)
        shutil.copyfile(self.out / f"actor_{self.iteration:04d}.pt", self.out / "actor_final.pt")
        shutil.copyfile(self.out / "critic_latest.pt", self.out / "critic_final.pt")
        result = {"iteration": self.iteration, "eval_base": base, "reused_periodic_check": reused,
                  "isolate_eval_rng": self.cfg.isolate_eval_rng, **metrics,
                  "finalize_s": round(time.perf_counter() - t0, 1)}
        (self.out / "final.json").write_text(json.dumps(result, indent=1))
        return result


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--hours", type=float, default=1.0)
    p.add_argument("--iterations", type=int, default=100_000)
    for field, default in asdict(Config()).items():
        kind = type(default)
        p.add_argument("--" + field.replace("_", "-"), type=(lambda s: s.lower() in ("1", "true")) if kind is bool
                       else kind, default=default)
    a = p.parse_args()
    cfg = Config(**{f: getattr(a, f) for f in asdict(Config())})
    if not np.isfinite(a.hours) or a.hours <= 0 or a.iterations < 1:
        p.error("hours and iterations must be positive")
    out = ROOT / "runs" / "vrpo" / a.name
    if out.exists() and any(out.iterdir()):
        p.error("run output is nonempty; use a fresh --name to preserve its evidence")
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(asdict(cfg), indent=1))
    native.set_rollout_chunk(128)
    torch.set_num_threads(1)
    learner = VRPO(cfg, out)
    t_end = time.time() + 3600 * a.hours
    while time.time() < t_end and learner.iteration < a.iterations:
        print(json.dumps(learner.iterate()), flush=True)
    # Final checking is additional to --hours; its cost is recorded separately.
    print(json.dumps({"final": learner.finalize()}), flush=True)


if __name__ == "__main__":
    main()
