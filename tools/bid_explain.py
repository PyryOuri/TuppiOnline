"""Fit readable models of the bot's RAMI/NOLO decision and test them.

Input: `tools/bid_dataset.py` rows. Models are fitted on the training deals
(point-count features chosen by forward selection on a validation split of
the training deals) and every number in the report is from the held-out deals:

* **agreement** with the bot's choice, overall and by how clear the bot's own
  preference was (|gap|: close < 0.002, medium, clear >= 0.01 equity);
* **regret**: the bot's own estimate of what following the rule loses per bid
  (|gap| wherever the rule picks the other contract), a cheap stand-in for the
  play test in `tools/bid_rule_eval.py`.

Output (`--out`): `report.json`, `report.md` (the rules in Finnish, the
tables) and the fitted models `model_*.json` for the play test.

    python tools/bid_explain.py --data runs/bidding/pilot/bids.jsonl.gz --out runs/bidding/pilot
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tuppi_ai import bid_models as bm  # noqa: E402
from tuppi_ai.bid_features import FEATURES  # noqa: E402

CANDIDATES = [f for f in FEATURES if f not in ("old_rami_score", "old_nolo_score")]
BANDS = (("close", 0.0, 0.002), ("medium", 0.002, 0.01), ("clear", 0.01, np.inf))


class OldRule:
    """The old reference bot's rule, unfitted: RAMI score >= 15 and NOLO score <= 2."""

    kind = "old_rule"

    def predict(self, rows):
        return np.array([r["old_rami_score"] >= 15.0 and r["old_nolo_score"] <= 2.0 for r in rows])

    def describe(self):
        return "Vanhan botin sääntö: RAMI-pisteet vähintään 15 ja NOLO-pisteet enintään 2."

    def to_json(self):
        return {"kind": self.kind}


def evaluate(model, rows) -> dict:
    y = np.array([r["bot_rami"] for r in rows])
    gap = np.array([r["gap"] for r in rows])
    pred = model.predict(rows)
    agree = pred == y
    regret = np.where(agree, 0.0, np.abs(gap))
    deals = np.array([r["deal"] for r in rows])
    out = {"n": int(len(rows)), "agreement": round(float(agree.mean()), 4),
           "rami_rate": round(float(pred.mean()), 4), "bot_rami_rate": round(float(y.mean()), 4),
           "regret_per_bid": round(float(regret.mean()), 5)}
    # a deal-clustered interval for the regret
    uniq = np.unique(deals)
    per_deal = np.array([regret[deals == d].sum() for d in uniq])
    counts = np.array([(deals == d).sum() for d in uniq])
    mean = per_deal.sum() / counts.sum()
    if len(uniq) > 1:
        var = len(uniq) / (len(uniq) - 1) * ((per_deal - mean * counts) ** 2).sum() / counts.sum() ** 2
        out["regret_ci"] = [round(float(mean - 1.96 * var ** 0.5), 5), round(float(mean + 1.96 * var ** 0.5), 5)]
    for name, lo, hi in BANDS:
        m = (np.abs(gap) >= lo) & (np.abs(gap) < hi)
        out[f"agreement_{name}"] = round(float(agree[m].mean()), 4) if m.any() else None
        out[f"share_{name}"] = round(float(m.mean()), 4)
    return out


def forward_select(train, gap, y, k_max: int) -> list[tuple[list[str], float]]:
    """Point-count feature sets of size 1..k_max, each chosen greedily by validation agreement."""
    deals = np.array([r["deal"] for r in train])
    val = deals % 5 == 1  # a fifth of the training deals (held-out deals are index % 10 == 0)
    fit_rows = [r for r, v in zip(train, val) if not v]
    val_rows = [r for r, v in zip(train, val) if v]
    g, yy = gap[~val], y[~val]
    yv = np.array([r["bot_rami"] for r in val_rows])
    chosen, path = ["hcp"], []
    while True:
        model = bm.PointCount(list(chosen)).fit(fit_rows, g, yy)
        path.append((list(chosen), float((model.predict(val_rows) == yv).mean())))
        if len(chosen) >= k_max:
            break
        best = None
        for f in CANDIDATES:
            if f in chosen:
                continue
            m = bm.PointCount(chosen + [f]).fit(fit_rows, g, yy)
            score = float((m.predict(val_rows) == yv).mean())
            if best is None or score > best[0]:
                best = (score, f)
        chosen.append(best[1])
    return path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--k-max", type=int, default=6)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.data, "rt") as fh:
        rows = [json.loads(line) for line in fh]
    train = [r for r in rows if not r["test"]]
    test = [r for r in rows if r["test"]]
    y = np.array([r["bot_rami"] for r in train], dtype=float)
    gap = np.array([r["gap"] for r in train])
    min_leaf = max(20, len(train) // 200)

    models = {"old_rule": OldRule(), "hcp_threshold": bm.Threshold("hcp").fit(train, y),
              "old_score_threshold": bm.Threshold("old_rami_score").fit(train, y)}
    path = forward_select(train, gap, y, args.k_max)
    for chosen, _ in path:
        models[f"point_count_{len(chosen)}"] = bm.PointCount(chosen).fit(train, gap, y)
    for depth in (2, 3, 4):
        models[f"tree_{depth}"] = bm.Tree(depth=depth, min_leaf=min_leaf).fit(train, y, CANDIDATES)

    report = {"rows": len(rows), "train": len(train), "test": len(test),
              "selection_path": [{"features": c, "validation_agreement": round(a, 4)} for c, a in path],
              "models": {}}
    for name, model in models.items():
        report["models"][name] = {"test": evaluate(model, test), "rule": model.describe(),
                                  "spec": model.to_json()}
        (args.out / f"model_{name}.json").write_text(json.dumps(model.to_json(), indent=1))
    (args.out / "report.json").write_text(json.dumps(report, indent=1))

    lines = ["# Botin tarjouslogiikka luettavina sääntöinä", "",
             f"{len(rows)} tarjouspäätöstä; säännöt sovitettu {len(train)} päätökseen, luvut "
             f"{len(test)} pidätetystä päätöksestä (eri jaot).", "",
             "| Malli | Yhtäpitävyys | tiukat | selvät | Hukka / tarjous | RAMI-osuus (botti) |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, entry in report["models"].items():
        t = entry["test"]
        lines.append(f"| {name} | {100 * t['agreement']:.1f} % | "
                     f"{100 * (t['agreement_close'] or 0):.0f} % | {100 * (t['agreement_clear'] or 0):.0f} % | "
                     f"{t['regret_per_bid']:.4f} | {100 * t['rami_rate']:.0f} % ({100 * t['bot_rami_rate']:.0f} %) |")
    lines += ["", "Hukka = botin oma arvio siitä, paljonko säännön noudattaminen maksaa tarjousta kohti "
              "(ottelun voittotodennäköisyys).", "", "## Säännöt", ""]
    for name, entry in report["models"].items():
        lines += [f"### {name}", "", "```", entry["rule"], "```", ""]
    (args.out / "report.md").write_text("\n".join(lines))
    print("\n".join(lines[:6 + len(models)]))


if __name__ == "__main__":
    main()
