# XI-PIB: Fail

One round of expert iteration from `best:w=128:pib=4:pibt=2:pibe=0.5` into VRPO3; 20-hour generation budget, seven workers, v3 bot-only games. Distillation used three epochs and learning rate 1e-4. Both evaluations used greedy networks without search and 4,096 duplicate base deals (32,768 games each), seed `xi-pib-eval-v1`.

Generated **477,021 rows** across 384 shards. The teacher differs from the lite bot on **21.1527%** of recorded decisions.

Fit: `final held-out agreement: search 0.6986 blueprint 0.8258`.

0–0 scores: equity/deal -0.001164; 95% CI [-0.001520, -0.000809]; deal wins 48.9929%; RAMI rate 79.6631%; 4,096 duplicate base deals.

Uniform scores: equity/deal -0.004128; 95% CI [-0.005210, -0.003047]; deal wins 48.6267%; RAMI rate 85.6598%; 4,096 duplicate base deals.

**Verdict: Fail.** The task's decision rule is: Pass when both point estimates exceed zero and at least one 95% interval excludes zero; Promising when both estimates exceed zero and both intervals include zero; Fail otherwise. These evaluations establish only the measured comparison against VRPO3 under these two score distributions.

Research commit: `067db0b378257b3537fcaf2f6db408b970192187`; setup commit: `2460d53e5247dd020d55af4b47ec8151c8618dcb`; engine commit: `dc554c4b3b0e48850a3570cab454c68841aa07fc`. Python 3.14.8; PyTorch 2.14.1+cu126; training device: cuda. The setup history and play-inference tests passed before generation. The only source change skips sudo when the system build dependencies are already installed.

Checkpoint SHA-256: `f8f1d1df40a354cef96c6b2a9d771eb8ab373c3481cb2c871856475a3e711017`.

Data shards remain local and are not included in this branch.
