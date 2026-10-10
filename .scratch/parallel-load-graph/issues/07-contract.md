# 07 implementation contract

Source of truth for ticket 07 (`07-resolve-conflicts-first.md`). Spec: `../spec.md` (stories 11, 13–19; "Pause and resume", "Schema changes", "Export"). Builds on `06-contract.md`, `04-contract.md`.

## Requested behavior
When the conflict check finds conflicts, the load pauses after merge, before drafting. The frontend shows each conflict with its source passages, notes and dates. The resident resolves every conflict by picking one documented value or typing a clarification; submitting resumes the load, which drafts and streams to done. Each resolution becomes a clinician-provided fact that keeps every original quote. The draft is built from resolved facts, never from the raw conflicting events. A case with no conflicts drafts without pausing. Export lists resolutions. The app never resolves a conflict on its own.

## User decisions
- If the draft's claims don't carry a resolution: treated as a validation error (one retry with the error fed back); if still missing, code appends a claim to `hospital_course` with the resolution text, the quotes' span IDs and the resolution link.
- Picking a documented value: the resolved text is `"{conflict description}: {chosen quote}"`, built by code.
- A claim carrying a resolution gets `support_status="needs_review"` and the resolution ID in `clinician_clarification_ids`, so the existing green "clarified by clinician — pending approval" badge and "Clinician-provided" line apply.
- `tests/test_summarize.py::test_case_001_draft_flags_only_the_medication_conflict` is unskipped (skipped in 06).

## Graph (core/load_graph.py)
`… merge → resolve → draft → END`
- **resolve**: no discrepancies → passes through. Otherwise calls `interrupt(conflicts)` and, on resume, receives the resolution inputs and returns `Resolution` objects. Discrepancy statuses become `clarified_pending_approval`.
- Compiled with an `InMemorySaver` checkpointer (serializer allowing the `core.models` types, as `core/review_graph.py` does). Each load uses a fresh `thread_id`. `max_concurrency=6` stays.
- **draft**: drafting gets (events minus raw conflicting events, resolutions). A raw conflicting event is one with any evidence whose quote range overlaps a conflict quote's range in the same span (both have `start`). Such events are dropped whole.
- Graph-level validation of resume input happens in the API (below); the node trusts it.

## Models (core/models.py)
- `Resolution { conflict_id, text, chosen_span_id: str | None, quotes: list[EvidenceRef], provenance: Literal["clinician-provided"] }`. `chosen_span_id` is set for a picked value, None for a typed clarification. `quotes` = all quotes of the conflict.
- The resolution ID used in `clinician_clarification_ids` is the conflict ID (`D01`…).

## Drafting (core/summarize.py)
- `generate_draft(events, spans, resolutions=())`.
- Prompt gets one line per resolution: `D01 | RESOLVED (clinician-provided) | {text} | spans: {quote span IDs}`, and a rule: state each resolved fact as written, cite its spans, put its ID in `clinician_clarification_ids`; never mention the superseded values as unresolved.
- Validation (inside the existing retry loop): unknown IDs in `clinician_clarification_ids` are removed (error); a resolution carried by no claim is an error.
- After the loop: claims carrying a resolution get every quote span of that resolution added to `evidence_span_ids` and `support_status="needs_review"`; others `unverified`. A still-missing resolution → appended `hospital_course` claim (next C number) + a warning naming the conflict.
- The old `needs_review`-event flagging and discrepancy building are removed (the graph sets discrepancies).

## API
- **Load SSE** (`POST /api/sessions/{id}/load`): as in 06; if conflicts exist, after `extraction_done` it sends `conflicts_found` and the stream ends (no `done`). Payload: `{conflicts: [{conflict_id, description, quotes: [{span_id, quote, document_id, filename, date, hospital_day, marker, text}]}]}`.
- **Resume** `POST /api/sessions/{id}/resolutions` body `{resolutions: [{conflict_id, chosen_span_id: str | null, clarification: str | null}]}` → SSE: `draft`, `done` (or `error`).
  - 404 unknown session. 409 `{"detail": "not paused"}` when the session is not waiting on conflicts (including a second concurrent submit).
  - 422 when: a conflict is missing, duplicated or unknown; both or neither of `chosen_span_id` / `clarification`; `chosen_span_id` not among that conflict's quote spans; blank clarification.
- **Session** (`api/sessions.py`): adds `conflicts` (list, JSON as in the payload above), `resolutions`, `paused`, `load_thread_id`. `load_running` stays true while paused (editing stays locked: ask/corrections/approve/export keep returning 409). A new load resets all of them and discards any pause.
- Drafting failure after resume → `error`, `load_running` false, `paused` false; Retry reruns the whole load.

## Export (core/export.py)
- `to_markdown(..., resolutions=())`. "Unresolved discrepancies" lists only `open` ones (else "None flagged."). New section "## Conflict resolutions": per resolution `- D01: {description} — "{text}" (clinician-provided; chosen from {marker} | typed clarification) {markers of all quotes}`, or "None." Quoted spans appear in the source appendix.
- The export endpoint passes the session's resolutions.

## Frontend (frontend/src/App.tsx)
- On `conflicts_found`: a "Resolve conflicts" panel. Per conflict: ID, description, and each quote's passage (marker, filename, date / hospital day, passage text) with a radio "Use this value"; plus a radio "Clarify" with a text input.
- "Resolve and continue" is disabled until every conflict has a pick or a non-blank clarification. Submitting POSTs resolutions and reads the returned SSE like the load stream (entries appended; `done` unlocks). A failed submit shows the error and keeps the panel.
- Step label while paused: "Waiting for conflict resolution".
- After resolution, the read-only Discrepancies list shows each discrepancy's resolution text as `Resolved (clinician-provided): {text}`.
- Claim badge: the existing green badge; the "Clinician-provided ({id})" line also looks up `resolutions` by conflict ID.
- Rebuilt `frontend/dist/` committed.

## Seams
- Model: stub `core.llm.parse` (as 06 tests do).
- Graph: `load_graph.stream(input | Command(resume=...), {"configurable": {"thread_id": ...}}, stream_mode="updates")`.
- API: TestClient on load + resolutions endpoints.

## Tests
- Fast:
  - with conflicts: load stream ends with `conflicts_found` and no summary call has been made; payload carries passage text, note and date;
  - resume with a pick and with a clarification: draft streams to done; the resolution text is in a claim with the resolution link, both quote spans, `needs_review`; raw conflicting events are not in the draft prompt; picked text = description + quote;
  - draft omitting a resolution → retried with an error naming it → still missing → appended `hospital_course` claim + warning;
  - no conflicts → no `conflicts_found`, straight to done;
  - every 422 and 409 case above; editing operations 409 while paused; a new load discards a pause;
  - export lists resolutions; frontend: panel renders passages, submit disabled until all resolved, submit streams to done and unlocks, resolution shown in discrepancy list and on the claim.
- Live (`-m live`): case_001 pauses on Medication A; resolving with clarification "Medication A 5 mg initially, 10 mg from Day 3" yields a draft claim stating it with both source citations. The shared live fixture resolves conflicts that way. The unskipped `test_summarize` test passes.

## Constraints
- No new dependencies. Every model call through `core.llm.parse`.
- Review graph and revise unchanged. Corrections still work on resolution claims.

## Out of scope
Per-section drafting (08); problem normalization (09); dedupe and its resolution guard (10); background retry (11); persistent checkpoints.

## Clarifications after test design
- The `Command(resume=...)` payload shape is the implementer's choice; resume is tested through the API.
- Edits test-architect made to 06 tests, `tests/conftest.py` and `tests/test_api.py::test_case_001_live_load` are accepted. They follow from the pause.
- `scripts/coverage.py` (dev tool, run standalone) passes a thread_id and, if the load pauses, resumes it by resolving each conflict with the same clarification the live fixture uses ("Medication A 5 mg initially, 10 mg from Day 3"). The app itself never resolves conflicts.
- "Unresolved discrepancies" lists discrepancies that have no resolution, not those with `status == "open"`. A ticket 04 correction sets `clarified_pending_approval` without resolving the conflict, and `test_api_ticket04` expects such a discrepancy to stay listed. (Planner decision after implementation.)
