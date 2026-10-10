# 12 implementation contract

Source of truth for ticket 12 (`12-section-event-routing.md`). Builds on `08-contract.md` through `11-contract.md`.

## Requested behavior
Each section call except the hospital course gets only the events routed to it, not every event. Each per-problem hospital-course call still gets that problem's events. Fewer repeated facts across sections should mean fewer claims before dedupe and faster drafting and dedupe. The ticket 11 redraft then covers only sections whose routed input changed.

## Baseline (measured 2026-10-10 on HEAD 63831d1, case_001, two runs)
| Run | Load → pause | Resume → done | Claims before dedupe | Removed | Final | Slowest section call | Dedupe call |
|---|---|---|---|---|---|---|---|
| 1 | 38.2 s | 45.3 s | 83 | 30 | 53 | 18.5 s | 26.8 s |
| 2 | 24.2 s | 46.1 s | 71 | 20 | 51 | 14.4 s | 28.4 s |

Measured with `$TMPDIR/measure.py`, which wraps `core.llm.parse` with timing and drives the API like the live fixture. The live test in this ticket records the same numbers after the change.

## Planner decisions (user delegated all open questions)
- **Who routes:** extraction does.
  - `ClinicalEvent` gains `sections: list[<section IDs other than hospital_course>] = []`. The type is a Literal built from `TEMPLATE`, so strict structured output cannot invent a section.
  - The per-note extraction prompt asks the model to tag each event with every section other than the hospital course that it belongs in, using the template purposes, which are listed from `TEMPLATE`. The prompt tells it to tag `[]` when the event belongs only in the hospital course.
  - Rejected alternatives:
    - a category mapping in code: a hard-coded guess that can starve sections;
    - a routing call after merge: one more round trip on the critical path.

  Extraction already runs per note, in parallel, with the full note context, and retried notes (ticket 11) get tags for free.
- **Events with no tags** go only to the hospital course, as before, by problem. They are not sent everywhere, since the hospital course is the catch-all.
- **Required sections are protected:** if a required section other than the hospital course has no routed events, it gets every non-conflicting event, as today, so that missing tags never make a required section read "Not documented". It does not trigger for optional sections.
- **Optional sections with nothing routed** (no events and no resolutions): no model call. The section is recorded as `documented: false`, and the stream sends `section_omitted` as today.
- **Resolutions:**
  - The hospital course gets each resolution through its mapped problem, as in 09.
  - A section other than the hospital course gets a resolution only when one of the raw conflicting events that overlap that conflict's quotes is tagged with that section. Those events are excluded from drafting themselves. For example, a dose conflict whose raw events were tagged `discharge_medications` reaches that section.
  - The 07 fallback still guarantees that every resolution is carried by at least one claim.
- **Ticket 11 redraft:**
  - A section other than the hospital course is affected only if its input changed: its routed events, or the fallback set for a required section that had no routed events.
  - Hospital-course problem groups are affected as in 11.
  - Comparing a section's routed events before and after the merge is enough. Event IDs are renumbered, so compare by content (statement and evidence span IDs), not by ID.
- **Unchanged:** dedupe (its timeout stays 60 s), the conflict check, normalization, numbering and streaming payloads.

## Tests
- Fast:
  - extraction keeps each event's `sections` tags, and the schema rejects a section ID that is not in the template or is `hospital_course`;
  - each section call other than the hospital course receives exactly its routed non-conflicting events;
  - an event with no tags reaches only the hospital-course call for its problem;
  - a required section with nothing routed gets every non-conflicting event;
  - an optional section with nothing routed makes no model call, and `section_omitted` is streamed;
  - a resolution reaches a section other than the hospital course only through its tagged raw conflicting events, and always reaches its problem's hospital-course call;
  - ticket 11 redraft: a recovered note whose events are tagged only `key_events` and belong to problem P redrafts `key_events` and the hospital-course group P only, plus any required section that was on the fallback because nothing was routed to it.
- Live (`-m live`):
  - the case_001 load records pre-dedupe claim count, final count, resume-to-done time and dedupe call time (printed, like the existing load wall-time print);
  - the draft still has `discharge_diagnoses` and `follow_up` claims, pneumonia and hypertension groups, and the D01 resolution with both quote spans;
  - every claim cites passages.

  The counts are recorded, not asserted. Model variance between runs is too large for a hard threshold.

## Constraints
- No new dependencies. Every model call goes through `core.llm.parse`.
- Earlier tests may be adapted where routing changes what a section call receives. Their stubs currently assume every section sees every event. Keep their behavioral assertions and list every edit.

## Out of scope
- Routing the hospital course by anything other than problem.
- Changing dedupe.
- Evaluating routing quality beyond the live checks.

## Clarifications after test design (planner)
- **Fallback set for a required section:** it includes untagged events, since it is every non-conflicting event.
- **Resolutions for a required section on the fallback:** it gets every resolution, the same as before routing.
- **Redraft input comparison:** routed events (or the fallback set) only, compared by statement and evidence span IDs. A newly routed resolution alone does not make a section affected.
- **What counts as "nothing routed":** no events and no resolutions. An optional section whose only input is a resolution still gets a call.
- **Accepted test-imposed interfaces:**
  - the `ExtractionResult` JSON schema has an `enum` of exactly the section IDs other than `hospital_course` on `sections` items;
  - session `events` serialize `sections`.
- **Accepted test edits:**
  - stub events tagged `EVERY_SECTION` in the 07/09/11/test_api tests;
  - `EVERY_SECTION` in `tests/section_stub.py`;
  - `resume_seconds` and `dedupe_seconds` in the `case001` fixture.
- Post-resolution (ticket 13 live run): a missed `discharge_diagnoses` tag dropped that optional section silently. Per user decision (option A), every section other than hospital_course with no tagged events now falls back to every non-conflicting event and every resolution; optional sections included. The 12 routing tests were updated to match. Live after the change: 32/32 passed; claims before dedupe 64 (removed 10); resume to done 33.7 s; dedupe 14.8 s.
