# Gameplay logging: legitimate-interest assessment

2026-10-27. Reviewed browser `f6c174f`, server `54e7cf0` and deployment
`4a2944e`, plus this notice update. Source inspection only: no saved games,
live provider settings or private records were opened.

## Purpose

The operator's concrete interests are running and securing a free game for
friends, recovering interrupted games, showing nickname standings, and
measuring/improving bots against human play. The intended basis for this
limited server-side processing is GDPR Article 6(1)(f), legitimate interests.
This rationale excludes advertising, selling data, identifying real people
and unrelated reuse. New purposes require reassessment and notice.

The operator determines these purposes. Render supplies hosting; its published
DPA describes processors, subprocessors and transfer safeguards. Actual account
terms/settings were not verified. Frankfurt configuration does not establish
that all processing stays within the EEA.

## Necessity

| Flow | Need and boundary |
| --- | --- |
| Room recovery | Seats/nicknames, credentials, cards and decisions support authoritative play and resumption. This does not justify indefinite named histories. |
| Chat | Delivery and recent history for participants/spectators; memory only in inspected code. |
| Standings | Nickname plus win/loss counts for the existing leaderboard; names are unverified and standings span rooms. |
| Bot development | Cards, actions, scores and bot version support replay and decision comparisons. Aggregate wins cannot reconstruct choices, and synthetic play does not capture the same human decisions. Names are unnecessary and excluded. |
| Results/security | Match identifiers support deduplication; short-window address handling supports abuse limits. Usage logs contain counters/timings. Infrastructure logs are separate. |

Development records exclude nicknames, room codes, session credentials, chat
and IP addresses. Their match ID is not a persistent person ID. Nevertheless,
matching cards/actions can link them to a named room or local save. Treat
linkable records as potentially personal; stripping fields is also processing.

## Balancing

The intended small audience, ordinary game subject matter and absence of
identity fields from development exports reduce impact. Private file permissions,
secret-protected exports and disabled application HTTP access logs provide
existing safeguards. No sensitive traits/contact details are requested.

The visible pre-play notice and settings now explain what is collected,
who can spectate, cross-room standings and linkability. Offline transmission
can be disabled using the existing setting. Its enabled default is not consent;
the switch is a transmission preference, not the legal basis for all processing.
A stranger may still not expect full game collection. The improved notice does
not retrospectively establish historical transparency.

Material limits remain:

- Online recording has no per-player off switch. Article 21 objections require
  an actual response and cessation where applicable; telling someone to stop
  playing is not a rights mechanism. Manual handling must account for copies
  and later records as necessary.
- The owner declined retention changes. Room-archive cleanup defaults to
  30 days/200 MiB. Development matches have a size cap; result summaries and
  nickname standings have no fixed expiry. Downloaded copies have no automatic
  expiry. Capacity limits alone do not prove continued retention is necessary.
- The owner declined publishing their name/email and has no project contact
  route. The notice respects that decision and states the absence. Article 13
  identity/contact information and a usable public rights-request route remain
  unresolved. The notice is not a complete GDPR notice.
- Nicknames can identify friends or be impersonated. Room-code holders can
  spectate cards/chat. The service is reachable by strangers; this assessment
  does not rely on the household exemption or whole-service authentication.

**Conclusion:** the purposes and selected fields support a specific, plausible
Article 6(1)(f) rationale. The above limits qualify the balancing assessment;
no unconditional compliance pass or permission for unlimited storage is given.
No retention, collection, defaults or access controls change in this work.

## Separate terminal-storage question

Saved games, sessions, settings, offline assets and research-send queues use
browser storage. Each use needs assessment under Finland's terminal-storage
rules. Legitimate interests does not replace consent where optional terminal
storage requires it, including any non-exempt research queue/preference.
This change makes no claim that every existing use is exempt and adds no banner.

## Evidence and sources

Code: browser `web/{preferences,app,presentation,storage}.mjs`; server
`src/tuppi_server/{rooms,research,results,leaderboard,limits,usage,hosted}.py`;
deployment `start.sh` and `render.yaml`. No secret values read.

Primary guidance checked 2026-10-27:

- [EDPB: legal bases and legitimate interests](https://www.edpb.europa.eu/sme/be-compliant/process-personal-data-lawfully_en).
- [EDPB: transparency and rights](https://www.edpb.europa.eu/sme/be-compliant/respect-individuals-rights_en).
- [EDPB: anonymisation](https://www.edpb.europa.eu/sme/be-compliant/secure-personal-data_en).
- [Traficom: terminal storage](https://www.kyberturvallisuuskeskus.fi/en/our-activities/regulation-and-supervision/cookies).
- [Render DPA](https://render.com/dpa), [subprocessors](https://render.com/security).

Reassess if purposes, audience, fields, recipients, objection handling, storage
or hosting change. This is internal documentation, not text shown to players.
