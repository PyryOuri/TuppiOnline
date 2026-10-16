# Self-paced Tuppi training preview

Version **0.3.2, build 26**, built 2026-10-04 from `TuppiClient-training`.

Open [Tuppi Training.app](<Tuppi Training.app>) or use the
[ZIP copy](Tuppi-Training-macOS.zip). Choose **Harjoittele päätöksiä → Tänään →
Aloita RAMI-kynnyksen mittaus** for the 40-hand RAMI test. It runs locally
without a server.

## Controls

- No countdown, fixed session duration or time limit. Pause and resume whenever
  useful; sessions saved by earlier previews still load.
- **R** selects RAMI; **N** selects NOLO.
- **Enter** locks the selected first answer. After locking, **Enter** moves to
  the next hand; after the last hand it opens the results.
- In ordinary decision exercises and practice games, the same game keyboard
  resolver handles **H/D/C/S**, followed by **2–9, 0/T, J/Q/K/A**. **1 then 0**
  also selects a ten. Left/right arrows move between legal cards in your chosen
  suit order. Card selection alone does not submit it; **Enter** confirms.
- Clicking an already chosen card deselects it, as in normal play.
- The RAMI measurement fixes the shown card, so its inputs are the contract
  keys R/N and Enter. Click the table to return keyboard focus after writing
  an optional reason.
- Existing **Command + / − / 0** display-size shortcuts remain available.

The decision lab and private practice/continuation tables share these controls.
Typing in a reason field uses that field; letter shortcuts are handled by the
focused table. Results remain hidden until all 40 first answers are committed.
The odds-window shortcut is disabled throughout protected measurement sessions,
including while paused.

## Results

**Kehitys** shows RAMI proportions, agreement with the frozen reference and an
exploratory threshold when fresh answers support fitting it. **Vastaukset ja
palaute** opens the recorded reason and numerical RAMI-versus-NOLO comparison.
This feedback still describes estimated values and uncertainty; detailed
card-specific bidding explanations have not been added.

The bank and eleven-task starter pilot are unchanged. The app continues using
the existing preview training-data directory and server URL
`http://127.0.0.1:18768`. Private games and interactive branches require that
server. Use one preview version at a time when saving training answers.

## Validation

- Full client suite: **155 tests, three optional snapshot skips, zero failures**.
- New checks cover contract/card keyboard input, legal-card arrow navigation,
  fixed-card probe inputs without early commitment/feedback, and loading legacy
  saved sessions after an unrestricted break.
- The existing RAMI tests and real localhost integration checks passed.
- GUI checking was attempted with a separate app ID and temporary training
  archive. Computer-use approval rejected opening that QA app, so keyboard
  event delivery and visual layout were not manually verified.
- [Package verification](PACKAGE_VERIFICATION.json), [test log](../swift-tests-v3.log),
  and [build log](../package-v3.log) record the delivered package.
- Live app and both earlier previews are preserved. The artifact is an unsigned
  local preview whose embedded runtime paths target this Mac.
