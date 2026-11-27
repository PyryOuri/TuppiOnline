Paste this into the session that owns the Colab branch, with TASK.md attached or pasted below it.

---

Next task on `claude/colab-pro-compute-eval-nu8in4`: Heidi 1.2 on the GPU, then a gated XI-CLEAN
pilot. The full brief is in TASK.md (from the Mac session).

In short:
- **Stage 1.** Give `lookahead.py` a default-off profile that plays Heidi 1.2's rules:
  - all legal candidates;
  - argmax with anchor margins 0.003 / 0.03;
  - W1024 and adaptive bid batches;
  - solver tail 6;
  - a separate float32 VRPO3 likelihood, mult 8;
  - VRPO1 rollouts.

  Test it against the engine. Validate it three ways: agreement with native Heidi against the
  native noise floor, a match against the Mac's Stage 0 reference, and throughput on an L4.
- **Stage 2.** Find the strongest affordable search around the suit-symmetry student. Continue
  only if it beats the plain student by at least +0.004.
- **Stage 3.** A pre-registered labelling and distillation pilot, judged by play, with a
  focus-label control.

Each gate can stop the line. Keep everything default-off. Report in the README and on Drive.
I start each stage and spend the Colab compute. Begin with Stage 1's code and CPU tests; tell me
when the Colab check is ready to run.
