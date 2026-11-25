"""T9: the rebuilt sooli-offer model against the exact heuristic (a small build)."""

from __future__ import annotations

import numpy as np
import torch

from tuppi_train import offer, tn
from tuppi_ai import native


def test_offer_model_small_build(net1, tmp_path):
    torch.manual_seed(0)
    dev = torch.device("cpu")
    summary = offer.build(tmp_path, net1, dev, offers=8000, games=2048, steps=1000)
    # the data: prefiltered offers are common, acceptances rare (offer_screen.py: about 2%)
    assert 0.3 < summary["offers_per_deal"] < 0.9
    assert 0.005 < summary["accept_rate"] < 0.06
    data = np.load(tmp_path / "train.npz")
    assert data["feat"].shape[1] == tn.FEAT1_BYTES and set(np.unique(data["label"])) <= {0, 1}
    # A build this small has about twenty accepted offers to validate on, so only a loose
    # sanity bound here; the full build's quality is reported by offer.validate (README).
    assert summary["auc"] > 0.55
    check = offer.validate(tmp_path / "offer_model.pt", net1, dev, offers=4000, games=2048)
    # same order of acceptance and of sooli deals as the exact heuristic, for far less time
    assert 0.3 < check["accept_model"] / check["accept_exact"] < 3
    assert 0.3 < check["sooli_share_model"] / check["sooli_share_exact"] < 3
    assert check["sooli_ms_per_deal_model"] < 0.5 * check["sooli_ms_per_deal_exact"]


def test_recorded_labels_are_the_engines_answers(net1):
    """With a model that always declines (a very negative bias), every recorded answer is a decline
    and no sooli is played: the recorder reports what the engine did."""
    from tuppi_ai.value import VNet
    never = VNet(8, 1, in_dim=native.feature_dim(1))
    with torch.no_grad():
        for p in never.parameters():
            p.zero_()
        never.out.bias.fill_(-50.0)
    mlp = native.Mlp(never, in_dim=never.config["in_dim"], out_dim=1)
    data = offer.record(net1, torch.device("cpu"), 500, games=1024, offer_model=mlp)
    assert len(data["label"]) >= 500 and data["label"].sum() == 0
    assert data["counts"]["sooli"] == 0
