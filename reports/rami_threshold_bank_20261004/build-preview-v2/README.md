# RAMI-threshold training preview

Built 2026-10-04 from the isolated `TuppiClient-training` checkout. Version
0.3.1, build 25, bundle ID `fi.tuppi.client.trainingpreview`.

Open [Tuppi Training.app](<Tuppi Training.app>). A ZIP copy is provided as
[Tuppi-Training-macOS.zip](Tuppi-Training-macOS.zip).

## Take the test

1. Choose **Harjoittele päätöksiä**.
2. On **Tänään**, choose **Aloita RAMI-kynnyksen mittaus**.
3. For each of 40 hands, choose RAMI or NOLO, set confidence, optionally write
   a reason, and choose **Lukitse ensimmäinen päätös**.
4. Choose **Seuraava tilanne**, or **Näytä tulokset** after the final hand.
   **Tallenna tauolle** preserves a session for later resumption.
5. On **Kehitys**, see the estimated threshold and bidding proportions. Open
   a hand under **Vastaukset ja palaute** to review your recorded reasoning
   and the reference estimate.

The RAMI test runs locally without a server. It contains 32 borderline hands
and eight comparison hands at 0–0, ten per bidding position. Bot feedback stays
hidden until all 40 first answers are committed. Familiar repeat hands are
separated from fresh first responses.

The feedback gives the estimated RAMI-versus-NOLO value difference and its
sampling uncertainty. It does not yet provide a detailed card-by-card account
of why the bot bid. These estimates describe a frozen model comparison; they
are not adjudicated right/wrong answers or a measure of human playing strength.

## Existing training features

The earlier eleven-task starter pilot is also bundled. For private games and
interactive branches, the existing isolated training server is configured at
`http://127.0.0.1:18768`; those features use the existing training runtime.

This preview keeps the earlier preview's training-data directory, allowing it
to read your existing training archive when opened. Packaging and tests did
not alter that archive. Use one preview version at a time when saving answers.
The app is an unsigned local preview; its embedded runtime paths target this Mac.

## Verification

- Full client suite: **151 tests, three optional snapshot skips, zero failures**.
- All three RAMI tests passed: prepared-bank checks, immutable answers and
  pause/resume, and complete-session reporting with repeat separation.
- Real localhost checks passed for ordinary play, locked bids/sooli and
  private-training game export/post-answer branches.
- See [PACKAGE_VERIFICATION.json](PACKAGE_VERIFICATION.json) for package,
  ZIP, bank and original-artifact hash checks.
- [Test log](../swift-tests-v2.log) and [release build log](../package-v2.log).
- Manual GUI inspection was not performed. Existing live app and earlier
  preview artifacts are preserved.

The packaging script gained optional preview-version environment settings;
its existing version defaults and normal-app settings are unchanged.
