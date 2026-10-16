# Expert save: bounded strength review

The owner supplied `/Users/pyryouri/Downloads/tuppi-tallennus.json` and
clarified that strength analysis takes priority over partner conventions.
The pre-round UI/policy prototype is paused, uncommitted and unqualified.

This is a review of one incomplete local match: one human (seat 0) with a
bot partner against two bots. The save identifies the 1024-world engine.
The player's expertise is owner-reported; the file does not identify them.

Before searching:

1. Verify the backup digest and replay all 36 deals and current position.
2. Report deal wins, contracts and score trajectory descriptively. Do not
   treat deals from one rising-score match as independent match outcomes.
3. Replay each completed deal using the frozen `9f28aa9` browser analysis
   engine and original WASM/models. At every non-forced human decision,
   run 1024-world search from that seat's observation only. Reset the bot
   context per deal, as the app's analysis does. Record every legal value,
   the incumbent anchored choice, the best searched choice, and the human
   choice. No card/lead preference is applied.
4. Use the app's existing descriptive categories for the gap from its
   recommended choice: below 0.01; 0.01–<0.04; >=0.04. Also show the gap
   from the maximum searched value separately, since the policy anchor
   sometimes deliberately keeps a lower searched value. Neither measure
   proves that the human made a mistake: finite search and its rollout
   opponent model can disagree with expert play.
5. Repeat up to 12 largest recommendation disagreements with a second,
   deterministic seed. These are selected diagnostic cases, not an unbiased
   second sample or a strength test. Replay the same recorded prefixes.
6. Keep all records local, do not fit models, change the bot, search for
   convention thresholds, deploy, or upload this player data. Search one
   decision at a time. Checkpoint each deal to allow continuation.

The partial 37th deal contributes to integrity checks and descriptive counts
only, not completed-deal results. Win counts, recommendation agreement and
estimated action gaps cannot establish overall strength, expected win rate,
causal losses or statistical superiority from this one unfinished match.
