# Why the bots bid RAMI so often (2026-10-02)

**The owner's question:** in human play RAMI is played in about 1/3 of
deals, but against the bot about 5/6. RAMI looks risky because of the
doubled stolen-RAMI penalty. Why do the bots prefer it, and is the
defenders' play optimised?

## Exploratory test E-R1 (pre-registered 2026-10-02, before its run)

**The question:** does the live bot over-bid RAMI against strong defence?
Its bid search models the opponents as the clone of v2, which defends worse
than the bot.

**The candidate:** the live configuration at W=128 with `rb=-0.02`. RAMI is
declared only when its searched value beats the best NOLO by more than 0.02.

**The opponent:** the same bot without the penalty, so bots defend on both
sides.

**The test:** 512 base deals, uniform scores, seed bvb-rami-v1, rs=1.

**Reading:**
- a lower bound above 0 means the bot over-bids against bot-strength
  defence;
- an upper bound below 0 means its bidding holds up against strong
  defence;
- otherwise the test is inconclusive.

This is a diagnosis, not a deployment test.
