# Where the record is empty

The findings index answers "has this been tried?". It cannot answer "what have we
never tried?", because an index contains only what happened. That second question
is the one the architecture review was asking when it said the attempts had been
"too narrow, too similar to each other".

`python -m tuppi_research.coverage` answers it by counting, not by opinion.

## 1. The diagnosis was wrong in its words and right in its substance

The record is **not** circular. 29 findings carry eight different verdicts — 11
measured, 5 inconclusive, 4 refuted, 3 confirmed, 3 constraint, and one each
rejected, killed and void. Only one experiment was a genuine repeat, the PIMC
revisit, and that was a retrieval failure caught by looking.

It is **concentrated**. Depth by dimension, over the same 29 findings:

| depth | dimension | |
| ---: | --- | --- |
| **0** | `adaptation` | Does the agent change during a match, or across matches? |
| **1** | `score_state` | Does play change with the match score? |
| 5 | `partnership` | What do partners communicate, and how? |
| 6 | `opponent` | Who is across the table? |
| 6 | `showing` | How is the contract chosen? |
| 7 | `observation` | What does the agent see? |
| 8 | `decision_scope` | At which decisions is extra effort spent? |
| 10 | `search` | Does the agent think ahead, and how much? |
| 11 | `scoring` | How are legal actions ranked? |
| 13 | `continuation` | What plays the rest of the deal? |
| 13 | `instrument` | Can the thing even be measured? |
| 17 | `endpoint` | What is counted as success? |

Seventeen findings about what to measure; **zero** about whether the agent should
change.

## 2. Why a coverage map rather than a hypothesis generator

Idea supply is not the scarce resource. The record already holds 8 negatable
assumptions, 10 blocked ones, 88 stated open questions and 2 admitted proposal
cards — against an experiment cost of minutes to hours, and a rate of roughly six
experiments in a working session. A generator that raises the *volume* of
candidates pours into a funnel whose neck is somewhere else.

What is scarce is **spread**. A proposal drawn from a depth-0 dimension is
structurally novel by construction, whatever its merit. That is the whole claim
of this module, and it is a modest one.

## 3. What it does not do

It proposes **regions, not mechanisms**. It can say that nothing in 29 findings
asks whether the agent should adapt; it cannot say what adaptation to build. The
mechanism still has to come from a person, and this only narrows where to look.

And `DIMENSIONS` is hand-written — the one input here that is not derived. A
dimension nobody thought to name stays invisible to this module exactly as it
stayed invisible to the programme, and that cannot be fixed by deriving the list
from the record, because the record is what is suspected of being narrow.

What *can* be done is to detect the list failing.
`coverage.unclaimed_findings()` reports any finding matching no dimension, and
`tests/research/test_coverage.py` fails on it. A finding in a region the list
does not name is proof the list has a hole. That converts an unfalsifiable worry
into a check — currently passing, with all 29 findings claimed.

Two dimensions are pinned at their current depth by a test. When `adaptation` or
`score_state` stops being empty, that test fails, and the failure is the signal
to re-read this document rather than a defect.

## 4. The first thing it found

`score_state` at depth 1 was already suspected: every experiment in this
programme ran at 0-0, and `docs/proposals/match-state-never-exercised.json`
proposes the test — `match_aware_v1` agrees with `partner_aware_v1` on 100.0% of
decisions at a level score, so an entire declared capability of the agent family
has never once been switched on.

`adaptation` at depth **0** was not suspected, and it is the larger hole. Every
policy in this repository is frozen and memoryless across deals. Whether an agent
that changes — within a match, or between them — is worth anything here has never
been asked, let alone answered. `src/tuppi_learning` exists; no finding cites it.

That is what a coverage map is for: the gap nobody was arguing about.
