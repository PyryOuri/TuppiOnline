"""XI-CLEAN: distil a stronger, lower-noise teacher into the lite bot (desktop job, 2026-10-19).

XI-PIB (results/xi-pib) failed: the student lost to VRPO3 (-0.00116 at 0-0,
-0.00413 at uniform scores), and the fit drove held-out agreement with the
teacher down from 0.784 to 0.699. Card-play entropy rose from 0.31 to 0.79
nats. Likely cause: hard labels from a W=128 teacher only about +0.005/deal
stronger than VRPO3, most of whose disagreements with VRPO3 are sampling noise.

This job changes the teacher and the labels, not the network:
- teacher: the live search with play inference at W=1024 (PIB4, T=2, eps=0.5);
- positions: reached by the lite bot itself (VRPO3 greedy on all seats);
- labels: per-world values of every legal card, kept only where the teacher's
  gain over the lite card is statistically clear (paired z over common worlds);
- fit: cross-entropy on those labels plus a KL anchor to VRPO3 on every row,
  selected on whole held-out shards.

Stages (docs/XI_CLEAN_TASK.md; tools/xi_clean_job.sh chains them):
  A  consistency  one card decision from each of 2,048 lite deals, priced by
                  W=128 and W=1024, two independent seeds each. Gate A: can
                  the W=1024 labels be trusted, and is there enough to gain?
  B  labels       lite deals; every card decision screened at W=128, W=1024
                  where the screen says it matters; resumable shards.
  C  fit          student from VRPO3; gate C on held-out shards.
  D  evaluate     student vs VRPO3 without search (tuppi_ai.evaluate), gate D.
  E  scale        more labels, refit, fresh-seed evaluation (only after D passes).

Every play-phase search reproduces the teacher's own computation
(SearchAgent.action_values -> native search_core with play inference), with
the world seed set per position.
"""
from __future__ import annotations

import argparse
import ctypes as C
import hashlib
import json
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEACHER = "best:w={w}:pib=4:pibt=2:pibe=0.5"
LITE = ROOT / "models" / "vrpo3_final.pt"

# Pre-registered constants (docs/XI_CLEAN_TASK.md). Do not tune after seeing results.
A_DEALS = 2048
CEILING_MIN = 0.0015      # gate A: equity/deal if the student copied every kept label
PRECISION_MIN = 0.8       # kept W=1024 deviations that an independent seed reproduces
Z_GRID = (2.0, 2.5, 3.0)
SCREEN_GRID = (0.0, 0.005, 0.01, 0.02)
RECALL_MIN = 0.9
MIN_GAP = 0.001           # a label needs at least this gain over the lite card
HOLDOUT_MOD = 10          # shards with index % 10 == 0 are held out
LAMBDAS = (0.3, 1.0, 3.0)
ROUNDS, ROUND_STEPS = 20, 100
DEV_BATCH, ANCHOR_BATCH = 512, 4096
LR = 3e-5
DEV_AGREE_MIN = 0.20
GUARD_AGREE = 0.97
GUARD_ENTROPY = 0.05
DEALS_PER_SHARD = 8

_W: dict = {}


def _seed(*parts) -> int:
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:8], "little")


def _jsonl(path: Path) -> list[dict]:
    """Rows of a progress ledger; a last line cut off by a shutdown is ignored."""
    rows = []
    if path.exists():
        for line in path.open():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def _dump(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    os.replace(tmp, path)


# ---------------------------------------------------------------- workers

def _init(w_lo: int, w_hi: int) -> None:
    import torch
    torch.set_num_threads(1)
    from tuppi_ai import evaluate, native
    native.set_rollout_chunk(128)   # least total work; same moves
    native.set_parallel(False)      # one thread per worker process
    native.set_belief_lanes(1)      # likewise for play-inference scoring
    _W["teacher"] = {w: evaluate._make_candidate(TEACHER.format(w=w)) for w in sorted({w_lo, w_hi})}
    _W["lite"] = evaluate._with_sooli(evaluate._make_candidate(str(LITE)), "v3")


def teacher_values(w: int, seat: int, obs, ids: list[int], seed: int) -> np.ndarray:
    """(w, len(ids)) per-world values for the acting team, as the teacher computes them."""
    from tuppi_ai import native
    agent = _W["teacher"][w][seat]
    sr = agent.searcher
    if obs.ruleset == 2:  # as SearchAgent.choose_action
        cfg = agent.sooli
        sr.env.set_sooli(cfg["belief"], False, cfg["offer_play_heur"], cfg["lam"])
    return native.search_world_values(sr.env, sr.mlp, obs, ids, w, sr.dd_left, C.c_uint64(seed))


def run_stats(pw: np.ndarray, ids: list[int], lite: int, grp: dict) -> dict:
    """Best card outside the lite card's equivalence group, its paired gain and z."""
    means = pw.mean(0)
    li = ids.index(lite)
    others = [j for j, a in enumerate(ids) if grp[a] != grp[lite]]
    alt = max(others, key=lambda j: (means[j], -j))
    d = pw[:, alt] - pw[:, li]
    gap = float(d.mean())
    se = float(d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 1 else float("inf")
    z = gap / se if se > 0 else (float("inf") if gap > 0 else 0.0)
    v = np.full(52, np.nan, np.float32)
    v[ids] = means
    return {"alt": ids[alt], "gap": gap, "z": z, "v": v}


def play_lite_deal(ns: str, index: int):
    """Yield (seat, observation, action) for one v3 deal with the lite bot on all seats."""
    from tuppi_engine import ExplicitDeal, apply_match_action, begin_explicit_deal, create_match, match_observation_for
    from tuppi_engine.state import ACTIVE_PHASES
    from tuppi_rules import MatchScore, RulesetId
    from tuppi_rules.cards import FULL_DECK

    rng = random.Random(f"xi-clean|{ns}|deal|{index}")
    cards = list(FULL_DECK)
    rng.shuffle(cards)
    hands = tuple(tuple(cards[s * 13:(s + 1) * 13]) for s in range(4))
    level = rng.randrange(13)  # the score distribution of evaluate.py --scores uniform
    score = (0, 0) if level == 0 else ((4 * level, 0) if rng.random() < 0.5 else (0, 4 * level))
    dealer = rng.randrange(4)
    match = create_match(initial_score=MatchScore(*score), initial_dealer=dealer, match_ref="xi-clean",
                         ruleset_id=RulesetId.PROJECT_TARGET_V3)
    state = begin_explicit_deal(match, ExplicitDeal(dealer=dealer, hands=hands))
    while state.phase in ACTIVE_PHASES:
        seat = state.current_actor
        observation = match_observation_for(state, seat)
        action = _W["lite"][seat].choose_action(observation)
        yield seat, observation, action
        state = apply_match_action(state, action)


def classify(observation, action):
    """None, or (obs, ids, lite id, groups, qualifies) for an unforced showing/card decision."""
    from tuppi_ai import native
    from tuppi_ai.bridge import action_id, obs_from_player_observation
    from tuppi_ai.equivalence import groups

    legal = observation.legal_actions
    if len(legal) < 2:
        return None
    obs = obs_from_player_observation(observation)
    if obs.phase not in (native.PH_SHOW, native.PH_PLAY) or obs.soolaaja >= 0:
        return None
    ids = [action_id(a) for a in legal]
    grp = {}
    for gi, members in enumerate(groups(obs, ids)):
        for a in members:
            grp[a] = gi
    qualifies = obs.phase == native.PH_PLAY and len(set(grp.values())) > 1
    return obs, ids, action_id(action), grp, qualifies


# ---------------------------------------------------------------- stage A

def task_a(chunk: int, per_chunk: int, w_lo: int, w_hi: int, out: str) -> dict:
    from tuppi_engine.trusted import trusted_transitions

    path = Path(out) / f"a_{chunk:05d}.npz"
    if path.exists():
        return {"chunk": chunk, "skipped": True}
    t0 = time.monotonic()
    rec: dict[str, list] = {}

    def put(key, value):
        rec.setdefault(key, []).append(value)

    for d in range(chunk * per_chunk, (chunk + 1) * per_chunk):
        decisions, per_team = [], [0, 0]
        with trusted_transitions():
            for seat, observation, action in play_lite_deal("A", d):
                c = classify(observation, action)
                if c and c[4]:
                    decisions.append((seat, c))
                    per_team[seat & 1] += 1
        if not decisions:
            continue
        pick = random.Random(f"xi-clean|A|pick|{d}").randrange(len(decisions))
        seat, (obs, ids, lite, grp, _) = decisions[pick]
        g = np.full(52, -1, np.int8)
        g[list(grp)] = list(grp.values())
        put("deal", d); put("seat", seat); put("lite", lite); put("grp", g); put("k", len(ids))
        put("n_played", obs.n_played); put("contract", obs.contract); put("per_team", sum(per_team) / 2)
        for w in (w_lo, w_hi):
            for run in ("a", "b"):
                c0 = time.process_time()
                st = run_stats(teacher_values(w, seat, obs, ids, _seed("A", d, pick, w, run)), ids, lite, grp)
                put(f"cpu_{w}{run}", time.process_time() - c0)
                for key in ("alt", "gap", "z", "v"):
                    put(f"{key}_{w}{run}", st[key])
    tmp = path.with_name("part_" + path.name)  # never matches a_*.npz / b_*.npz
    np.savez(tmp, **{k: np.array(v) for k, v in rec.items()})
    os.replace(tmp, path)
    return {"chunk": chunk, "rows": len(rec.get("deal", [])), "seconds": round(time.monotonic() - t0, 1)}


def _load(paths) -> dict:
    parts = [dict(np.load(p)) for p in paths]
    parts = [p for p in parts if p and len(next(iter(p.values())))]
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]} if parts else {}


def _mean_se(x: np.ndarray) -> tuple[float, float]:
    x = np.asarray(x, float)
    return float(x.mean()), float(x.std(ddof=1) / math.sqrt(len(x))) if len(x) > 1 else float("inf")


def analyse_a(out: Path, w_lo: int, w_hi: int) -> dict:
    a = _load(sorted(out.glob("a_*.npz")))
    n = len(a["deal"])
    rows = np.arange(n)
    D = float(a["per_team"].mean())  # unforced multi-group card decisions per team per deal
    res = {"positions": n, "card_decisions_per_team_per_deal": D, "by_worlds": {}}
    for w in (w_lo, w_hi):
        gap_a, z_a, alt_a, alt_b = a[f"gap_{w}a"], a[f"z_{w}a"], a[f"alt_{w}a"], a[f"alt_{w}b"]
        va, vb = a[f"v_{w}a"], a[f"v_{w}b"]
        dev_a, dev_b = gap_a > 0, a[f"gap_{w}b"] > 0
        same = a["grp"][rows, alt_a] == a["grp"][rows, alt_b]
        repro = dev_a & dev_b & same
        cross = vb[rows, alt_a] - vb[rows, a["lite"]]  # seed b's estimate of following seed a
        best_a = np.where(dev_a, a["grp"][rows, alt_a], a["grp"][rows, a["lite"]])
        best_b = np.where(dev_b, a["grp"][rows, alt_b], a["grp"][rows, a["lite"]])
        r = {"deviation_rate": float(dev_a.mean()), "self_agreement": float((best_a == best_b).mean()),
             "deviation_reproduced": float(repro[dev_a].mean()) if dev_a.any() else None,
             "cpu_per_position_s": float(np.mean(a[f"cpu_{w}a"])), "filters": {}}
        for t in (0.0,) + Z_GRID:
            keep = dev_a & (z_a >= t) & (gap_a >= MIN_GAP)
            f, se = _mean_se(np.where(keep, cross, 0.0))
            r["filters"][str(t)] = {"kept_share": float(keep.mean()),
                                    "precision": float(repro[keep].mean()) if keep.any() else None,
                                    "follow_value_per_decision": f, "se": se,
                                    "ceiling_per_deal": D * f, "ceiling_lo95": D * (f - 1.96 * se)}
        for name, sel in (("nolo", a["contract"] == 0), ("rami", a["contract"] == 1)):
            if sel.any():
                r[name] = {"positions": int(sel.sum()), "deviation_rate": float(dev_a[sel].mean()),
                           "follow_value_per_decision": float(np.where(dev_a, cross, 0.0)[sel].mean())}
        res["by_worlds"][str(w)] = r
    hi = res["by_worlds"][str(w_hi)]["filters"]
    t_star = next((t for t in Z_GRID if (hi[str(t)]["precision"] or 0) >= PRECISION_MIN), Z_GRID[-1])
    lab = (a[f"gap_{w_hi}a"] > 0) & (a[f"z_{w_hi}a"] >= t_star) & (a[f"gap_{w_hi}a"] >= MIN_GAP)
    screen = {}
    for m in SCREEN_GRID:
        s = a[f"gap_{w_lo}a"] > -m
        screen[str(m)] = {"recall": float(s[lab].mean()) if lab.any() else None, "share": float(s.mean())}
    margin = next((m for m in SCREEN_GRID if (screen[str(m)]["recall"] or 0) >= RECALL_MIN), None)
    chosen = hi[str(t_star)]
    passed = chosen["ceiling_per_deal"] >= CEILING_MIN and chosen["ceiling_lo95"] > 0
    res.update({"z_threshold": t_star, "screen": screen, "screen_margin": margin,
                "gate": "pass" if passed else "fail",
                "gate_rule": f"ceiling at the chosen z >= {CEILING_MIN} and its lower 95% bound > 0"})
    return res


# ---------------------------------------------------------------- stage B / E

def task_b(shard: int, deals: int, w_lo: int, w_hi: int, t_star: float, margin, out: str) -> dict:
    from tuppi_ai import native
    from tuppi_engine.trusted import trusted_transitions

    path = Path(out) / f"b_{shard:05d}.npz"
    if path.exists():
        return {"shard": shard, "skipped": True}
    t0, c0 = time.monotonic(), time.process_time()
    dim = native.feature_dim(2)
    feat = np.zeros((1, dim), np.uint8)
    rec: dict[str, list] = {}
    nan52 = np.full(52, np.nan, np.float32)
    counts = {"rows": 0, "qualifying": 0, "screened": 0, "labels": 0, "errors": 0}
    holdout = shard % HOLDOUT_MOD == 0
    for j in range(deals):
        index = shard * deals + j
        i = 0
        with trusted_transitions():
            for seat, observation, action in play_lite_deal("B", index):
                c = classify(observation, action)
                if not c:
                    continue
                obs, ids, lite, grp, q = c
                i += 1
                native.encode(obs, feat[0], 2)
                mask = np.zeros(native.NUM_ACTIONS, np.uint8)
                mask[ids] = 1
                g = np.full(52, -1, np.int8)
                if obs.phase == native.PH_PLAY:
                    g[list(grp)] = list(grp.values())
                row = {"feat": np.packbits(feat[0]), "mask": np.packbits(mask), "phase": obs.phase,
                       "lite": lite, "deal": index, "team": seat & 1, "contract": obs.contract,
                       "n_played": obs.n_played, "qual": q, "grp": g, "target": -1, "screened": False,
                       "z": np.nan, "gap": np.nan, "v_lo": nan52, "v_hi": nan52, "v_hc": nan52}
                if q:
                    counts["qualifying"] += 1
                    try:
                        lo = run_stats(teacher_values(w_lo, seat, obs, ids, _seed("B", index, i, "lo")), ids, lite, grp)
                        row["v_lo"] = lo["v"]
                        if margin is None or lo["gap"] > -margin:
                            hi = run_stats(teacher_values(w_hi, seat, obs, ids, _seed("B", index, i, "hi")),
                                           ids, lite, grp)
                            row.update(screened=True, z=hi["z"], gap=hi["gap"], v_hi=hi["v"])
                            counts["screened"] += 1
                            if hi["gap"] >= MIN_GAP and hi["z"] >= t_star:
                                row["target"] = hi["alt"]
                                counts["labels"] += 1
                            if holdout:  # an independent price for unbiased held-out gains
                                hc = run_stats(teacher_values(w_hi, seat, obs, ids, _seed("B", index, i, "hc")),
                                               ids, lite, grp)
                                row["v_hc"] = hc["v"]
                    except RuntimeError:
                        counts["errors"] += 1
                for k, v in row.items():
                    rec.setdefault(k, []).append(v)
                counts["rows"] += 1
    tmp = path.with_name("part_" + path.name)  # never matches a_*.npz / b_*.npz
    np.savez(tmp, deals=np.array([deals]), **{k: np.array(v) for k, v in rec.items()})
    os.replace(tmp, path)
    return {"shard": shard, **counts, "seconds": round(time.monotonic() - t0, 1),
            "cpu_s": round(time.process_time() - c0, 1)}


# ---------------------------------------------------------------- stage C

def fit(out: Path, stage: str, smoke: bool) -> dict:
    import torch

    from tuppi_ai import model as qmodel
    from tuppi_ai import native

    paths = sorted(out.glob("b_*.npz"))
    data = _load(paths)
    shard_of = np.concatenate([np.full(len(np.load(p)["lite"]), int(p.stem[2:])) for p in paths])
    deals_per = {int(p.stem[2:]): int(np.load(p)["deals"][0]) for p in paths}
    n = len(data["lite"])
    hold = shard_of % HOLDOUT_MOD == 0
    if smoke and (hold.all() or not hold.any()):
        hold = data["deal"] % 2 == 0
    dev = data["target"] >= 0
    card = data["phase"] == native.PH_PLAY
    show = data["phase"] == native.PH_SHOW
    tr_all, tr_dev = np.flatnonzero(~hold), np.flatnonzero(~hold & dev)
    h_dev, h_card_nd, h_show = np.flatnonzero(hold & dev), np.flatnonzero(hold & card & ~dev), np.flatnonzero(hold & show)
    h_qual = np.flatnonzero(hold & data["qual"])
    dim = native.feature_dim(2)
    device = torch.device("cuda" if torch.cuda.is_available() else
                          "mps" if torch.backends.mps.is_available() else "cpu")
    try:
        torch.ones(1, device=device).sum().item()
    except Exception:
        device = torch.device("cpu")
    ref = qmodel.load(LITE, device).eval()
    rows = np.arange(n)

    def batch(idx):
        x = np.unpackbits(data["feat"][idx], axis=1)[:, :dim]
        m = np.unpackbits(data["mask"][idx], axis=1)[:, :native.NUM_ACTIONS]
        return torch.from_numpy(x).to(device), torch.from_numpy(m).to(device).bool()

    def logits(net, x, m):
        return net(x).masked_fill(~m, -1e9)

    def holdout_metrics(net) -> dict:
        net.eval()
        pick = np.full(n, -1)
        ent = np.zeros(n)
        ent_ref = np.zeros(n)
        idx_all = np.unique(np.concatenate([h_dev, h_card_nd, h_show, h_qual]))
        with torch.no_grad():
            for s in range(0, len(idx_all), 16384):
                idx = idx_all[s:s + 16384]
                x, m = batch(idx)
                for model_, e in ((net, ent), (ref, ent_ref)):
                    lp = torch.log_softmax(logits(model_, x, m), 1)
                    e[idx] = (-(lp.exp() * lp.masked_fill(~m, 0.0)).sum(1)).cpu().numpy()
                    if model_ is net:
                        pick[idx] = lp.argmax(1).cpu().numpy()
        net.train()
        g = data["grp"]
        res = {"dev_agreement": float((g[h_dev, pick[h_dev]] == g[h_dev, data["target"][h_dev]]).mean())
               if len(h_dev) else None,
               "card_agreement_nondev": float((g[h_card_nd, pick[h_card_nd]] == g[h_card_nd, data["lite"][h_card_nd]]).mean())
               if len(h_card_nd) else None,
               "show_agreement": float((pick[h_show] == data["lite"][h_show]).mean()) if len(h_show) else None,
               "card_entropy_delta": float((ent - ent_ref)[np.flatnonzero(hold & card)].mean())
               if (hold & card).any() else None}
        # predicted gain: independent W_hi price where held-out rows have one, else the W_lo screen
        # price (conservative: those rows were screened out because the lite card looked best)
        moved = h_qual[g[h_qual, pick[h_qual]] != g[h_qual, data["lite"][h_qual]]]
        gain = np.zeros(n)
        if len(moved):
            v = np.where(np.isnan(data["v_hc"][moved]).all(1, keepdims=True), data["v_lo"][moved], data["v_hc"][moved])
            gain[moved] = np.nan_to_num(v[np.arange(len(moved)), pick[moved]] - v[np.arange(len(moved)), data["lite"][moved]])
        per_shard = []
        for s in np.unique(shard_of[hold]):
            sel = hold & (shard_of == s)
            per_shard.append(gain[sel].sum() / (2 * deals_per[int(s)]))  # per team per deal
        mean, se = _mean_se(np.array(per_shard)) if per_shard else (0.0, float("inf"))
        res.update(moved_share=float(len(moved) / max(len(h_qual), 1)), predicted_gain_per_deal=mean,
                   predicted_gain_lo95=mean - 1.96 * se)
        return res

    candidates = []
    base = holdout_metrics(qmodel.load(LITE, device).train())
    lambdas, rounds = ((1.0,), 1) if smoke else (LAMBDAS, ROUNDS)
    steps = 5 if smoke else ROUND_STEPS
    best_net, best_key, best_row = None, None, None
    for li, lam in enumerate(lambdas):
        torch.manual_seed(1000 + li)
        rng = np.random.default_rng(1000 + li)
        net = qmodel.load(LITE, device).train()
        opt = torch.optim.AdamW(net.parameters(), lr=LR, weight_decay=0.0)
        for r in range(1, rounds + 1):
            for _ in range(steps):
                loss = torch.zeros((), device=device)
                if len(tr_dev):
                    idx = tr_dev[rng.integers(0, len(tr_dev), DEV_BATCH)]
                    x, m = batch(idx)
                    loss = loss + torch.nn.functional.cross_entropy(
                        logits(net, x, m), torch.from_numpy(data["target"][idx].astype(np.int64)).to(device))
                idx = tr_all[rng.integers(0, len(tr_all), ANCHOR_BATCH)]
                x, m = batch(idx)
                with torch.no_grad():
                    lr_ = torch.log_softmax(logits(ref, x, m), 1)
                ls = torch.log_softmax(logits(net, x, m), 1)
                kl = torch.where(m, lr_.exp() * (lr_ - ls), torch.zeros_like(ls)).sum(1).mean()
                loss = loss + lam * kl
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step()
            met = holdout_metrics(net)
            guard = ((met["show_agreement"] is None or met["show_agreement"] >= GUARD_AGREE)
                     and (met["card_agreement_nondev"] is None or met["card_agreement_nondev"] >= GUARD_AGREE)
                     and (met["card_entropy_delta"] is None or met["card_entropy_delta"] <= GUARD_ENTROPY))
            row = {"lambda": lam, "round": r, "steps": r * steps, "guard": guard, **met}
            candidates.append(row)
            print(json.dumps(row), flush=True)
            key = met["predicted_gain_per_deal"]
            if guard and (best_key is None or key > best_key):
                best_key, best_net = key, {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
                best_row = row
    student = out / f"student_{stage}.pt"
    res = {"stage": stage, "rows": n, "shards": len(paths), "train_labels": int(len(tr_dev)),
           "holdout_labels": int(len(h_dev)), "device": str(device), "baseline": base, "candidates": candidates}
    if best_net is None:
        res.update(selected=None, gate="fail", reason="no candidate met the guards")
    else:
        net = qmodel.load(LITE, "cpu")
        net.load_state_dict(best_net)
        qmodel.save(net, student, xi_clean={"stage": stage, "selected": best_row})
        ok = ((best_row["dev_agreement"] or 0) >= DEV_AGREE_MIN and best_row["predicted_gain_per_deal"] > 0
              and best_row["predicted_gain_lo95"] > 0)
        res.update(selected=best_row, student=str(student), gate="pass" if ok else "fail",
                   gate_rule=f"guards hold, held-out label agreement >= {DEV_AGREE_MIN}, "
                             "predicted gain > 0 with lower 95% bound > 0")
    return res


# ---------------------------------------------------------------- gates and summary

def strength_verdict(z: dict, u: dict) -> str:
    pos = z["equity_per_deal"] > 0 and u["equity_per_deal"] > 0
    excl = z["ci95"][0] > 0 or u["ci95"][0] > 0
    return "pass" if pos and excl else "promising" if pos else "fail"


def gate(out: Path, name: str) -> bool:
    if name == "A":
        return json.loads((out / "A.json").read_text())["gate"] == "pass"
    if name in ("C_d", "C_e"):
        return json.loads((out / f"fit_{name[-1]}.json").read_text())["gate"] == "pass"
    stage = name.lower()
    z, u = (json.loads((out / f"eval_{stage}_{s}.json").read_text()) for s in ("zero", "uniform"))
    verdict = strength_verdict(z, u)
    _dump(out / f"verdict_{stage}.json", {"stage": name, "verdict": verdict})
    return verdict == "pass"


def summary(out: Path) -> dict:
    s: dict = {"job": "xi-clean", "out": str(out)}
    if (out / "A.json").exists():
        a = json.loads((out / "A.json").read_text())
        s["A"] = {k: a[k] for k in ("positions", "gate", "z_threshold", "screen_margin",
                                     "card_decisions_per_team_per_deal")}
        s["A"]["by_worlds"] = {w: {k: r[k] for k in ("deviation_rate", "self_agreement", "deviation_reproduced",
                                                     "cpu_per_position_s")}
                               | {"chosen_filter": r["filters"][str(a["z_threshold"])]}
                               for w, r in a["by_worlds"].items()}
    for stage in ("B", "E"):
        prog = out / f"progress_{stage}.jsonl"
        if prog.exists():
            rows = [r for r in _jsonl(prog) if "rows" in r]
            s[stage] = {k: sum(r[k] for r in rows) for k in ("rows", "qualifying", "screened", "labels", "errors")}
            s[stage]["shards"] = len(rows)
    for stage in ("d", "e"):
        f = out / f"fit_{stage}.json"
        if f.exists():
            r = json.loads(f.read_text())
            s[f"C_{stage}"] = {k: r.get(k) for k in ("gate", "train_labels", "holdout_labels", "device", "selected",
                                                      "baseline", "reason")}
        ev = {}
        for sc in ("zero", "uniform"):
            p = out / f"eval_{stage}_{sc}.json"
            if p.exists():
                r = json.loads(p.read_text())
                ev[sc] = {k: r[k] for k in ("equity_per_deal", "ci95", "base_deals", "won", "rami", "seconds")}
        if ev:
            s[f"eval_{stage}"] = ev
        v = out / f"verdict_{stage}.json"
        if v.exists():
            s[f"verdict_{stage}"] = json.loads(v.read_text())["verdict"]
    s["stopped_at"] = next((g for g, ok in (("A", s.get("A", {}).get("gate") == "fail"),
                                            ("C_d", s.get("C_d", {}).get("gate") == "fail"),
                                            ("D", s.get("verdict_d") not in (None, "pass")),
                                            ("C_e", s.get("C_e", {}).get("gate") == "fail")) if ok), None)
    _dump(out / "SUMMARY.json", s)
    return s


# ---------------------------------------------------------------- driver

def _pool(workers: int, w_lo: int, w_hi: int) -> ProcessPoolExecutor:
    # A fresh process per task keeps worker memory flat over a long run.
    return ProcessPoolExecutor(workers, initializer=_init, initargs=(w_lo, w_hi), max_tasks_per_child=1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--smoke", action="store_true", help="tiny sizes, W=16/32: checks the pipeline, not strength")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("consistency"); p.add_argument("--workers", type=int, default=7)
    p = sub.add_parser("labels"); p.add_argument("--workers", type=int, default=7)
    p.add_argument("--hours", type=float, default=24.0); p.add_argument("--stage", choices=("B", "E"), required=True)
    p = sub.add_parser("fit"); p.add_argument("--stage", choices=("d", "e"), required=True)
    p = sub.add_parser("gate"); p.add_argument("name", choices=("A", "C_d", "D", "C_e", "E"))
    sub.add_parser("summary")
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    w_lo, w_hi = (16, 32) if args.smoke else (128, 1024)
    os.environ.setdefault("TUPPI_AI_SERIAL", "1")

    if args.cmd in ("consistency", "labels"):  # the job runs one stage at a time
        for stale in out.glob("part_*.npz"):  # left by an interrupted task; that task reruns
            stale.unlink()
    if args.cmd == "consistency":
        deals, per = (8, 4) if args.smoke else (A_DEALS, 16)
        log = (out / "progress_A.jsonl").open("a")
        with _pool(args.workers, w_lo, w_hi) as pool:
            futs = [pool.submit(task_a, c, per, w_lo, w_hi, str(out)) for c in range(deals // per)]
            for f in as_completed(futs):
                row = f.result() | {"time": time.strftime("%Y-%m-%d %H:%M:%S")}
                log.write(json.dumps(row) + "\n"); log.flush()
                print(json.dumps(row), flush=True)
        res = analyse_a(out, w_lo, w_hi)
        _dump(out / "A.json", res)
        print(json.dumps(res, indent=1))
    elif args.cmd == "labels":
        a = json.loads((out / "A.json").read_text())
        t_star, margin = a["z_threshold"], a["screen_margin"]
        # The budget is cumulative over restarts: worker time of finished shards (from the
        # progress ledger, appended as each shard completes) divided by the worker count.
        prog = out / f"progress_{args.stage}.jsonl"
        used = sum(r.get("seconds", 0.0) for r in _jsonl(prog) if "rows" in r)
        budget = args.hours * 3600 * args.workers
        print(json.dumps({"stage": args.stage, "budget_hours": args.hours, "used_hours": used / 3600 / args.workers}),
              flush=True)
        limit = (4 if args.stage == "B" else 6) if args.smoke else 10 ** 6
        per = 1 if args.smoke else DEALS_PER_SHARD
        todo = (i for i in range(limit) if not (out / f"b_{i:05d}.npz").exists())
        log = (out / f"progress_{args.stage}.jsonl").open("a")
        with _pool(args.workers, w_lo, w_hi) as pool:
            running = set()
            for _ in range(args.workers if used < budget else 0):
                i = next(todo, None)
                if i is not None:
                    running.add(pool.submit(task_b, i, per, w_lo, w_hi, t_star, margin, str(out)))
            while running:
                done = next(as_completed(running))
                running.remove(done)
                row = done.result() | {"time": time.strftime("%Y-%m-%d %H:%M:%S")}
                log.write(json.dumps(row) + "\n"); log.flush()
                print(json.dumps(row), flush=True)
                used += row.get("seconds", 0.0)
                if used < budget:
                    i = next(todo, None)
                    if i is not None:
                        running.add(pool.submit(task_b, i, per, w_lo, w_hi, t_star, margin, str(out)))
    elif args.cmd == "fit":
        res = fit(out, args.stage, args.smoke)
        _dump(out / f"fit_{args.stage}.json", res)
        print(json.dumps({k: v for k, v in res.items() if k != "candidates"}, indent=1))
    elif args.cmd == "gate":
        ok = gate(out, args.name)
        print(f"gate {args.name}: {'pass' if ok else 'fail'}")
        sys.exit(0 if ok else 1)
    else:
        print(json.dumps(summary(out), indent=1))


if __name__ == "__main__":
    main()
