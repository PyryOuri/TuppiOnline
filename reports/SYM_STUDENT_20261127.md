# Suit-symmetry student on the release bots, and a GPU Heidi / XI-CLEAN task (Mac session, 2026-11-27)

This branch has two report directories:

- `reports/tuppi_sym_student_20261126/`: the Colab student (`sym_preflight_v1`, `best_student.pt`),
  converted and measured on the released code.
  - Nelli (lite C1H) on the student vs Nelli 1.1: +0.00637 [+0.00559, +0.00716] per deal at
    uniform scores (8,192 base deals), and 62.4% of 3,500 complete-match pairs.
  - The plain network: +0.00319 at 0-0, +0.00740 at uniform.
  - `README.md` has the checks, costs and results.
  - The large per-deal result files (plain and Nelli duplicates, 36 MB) stay on the Mac;
    summaries, ledgers and the match-pair file are here.
- `reports/tuppi_gpu_heidi_xi_20261127/`: `TASK.md` and `PROMPT.md`, a proposed task for the
  session that owns `claude/colab-pro-compute-eval-nu8in4`.
  - What it proposes: Heidi 1.2's rules on top of its GPU look-ahead, validated against native
    Heidi, then a gated XI-CLEAN pilot.
  - Written before reading that branch fully; that session decides what is useful.

The code is on branch `ai/research/sym-student-20261126`: the TuppiAI release source ac94273 plus
two commits.

| Path | Contents |
|---|---|
| `models/vrpo4sym_v1.pt` | the student (sha256 5322bd22…) |
| `models/vrpo4sym_v1.lite.npz` | its lite file (sha256 88c2ea62…) |
| `tools/stage3_eval.py`, `tools/ledger.py` | Stage 3's evaluator and ledger |
| `tools/sym_student_check.py` | the conversion check |
| `tools/sym_student_compare.sh` | the comparison driver, including the prepared `nelli_heidi` step: Nelli on the student vs Heidi 1.2 at W1024, not run yet |
| `tools/sym_student_report.py` | the report |

Nothing here changes a product or release.
