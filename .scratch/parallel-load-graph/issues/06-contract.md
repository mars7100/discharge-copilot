# 06 implementation contract

Source of truth for ticket 06 (`06-parallel-extraction.md`). Spec: `../spec.md` (stories 4, 5, 7, 11, 12, 13, 47, 52; "Phase 1 nodes", "Concurrency"). Builds on `03a-contract.md`, `04-contract.md`.

## Requested behavior
Loading extracts each note in its own model call, all running concurrently (cap 6). Alongside them, one conflict-check call reads all passages and returns only conflicts, each with a verbatim quote from every conflicting passage. A merge step orders and numbers events deterministically and validates quotes. Events gain a `problem` label. Conflicts become the draft's discrepancies. The resident sees each note reported as it finishes. A note whose extraction fails does not fail the load.

## User decisions
- Until 07, conflicts map directly to `Draft.discrepancies`. Extraction no longer sets `needs_review`, so no claim gets `support_status="needs_review"` from this pipeline (badges stay dark until 07).
- `extraction_done` stays (sent once, after merge). `note_extracted` / `note_failed` are added per note.
- A note that fails after its validation retry is skipped and the load continues. No background retry (ticket 11).

## Graph (core/load_graph.py)
`START → [extract_note × N (Send, one per document), conflict_check] → merge → draft → END`
- **extract_note**: calls `core.extract.extract_events([doc], spans_of_that_doc)`. Success → returns that note's events, warnings and `document_id`. `ExtractionError` (or any exception after its internal retry) → returns a failure record `{document_id, detail}` and no events. Never raises.
- **conflict_check**: one `llm.parse` call over all documents and passages, returns conflict items. Runs concurrently with the per-note branches. A failure after its own retry fails the load (spec assumption: conflicts gate drafting).
- **merge**: waits for all branches and the conflict check.
  - Events sorted by (document position in `documents`, smallest `order` of the event's cited spans, the model's index within that note); then numbered `E01…`. Numbering depends only on model output, never on completion order.
  - Conflicts numbered `D01…` in order of (document position, span order) of their first quote.
  - If every note failed → the load fails (error event), as today when extraction yields no events.
- **draft**: `core.summarize.generate_draft(events, spans)` unchanged in signature; the resulting draft's `discrepancies` are replaced by those built from conflicts (`description`, `source_span_ids` = the conflict's quoted span IDs, status `open`).
- `max_concurrency=6` is applied to the compiled `load_graph` itself (callers don't pass it).

## Extraction (core/extract.py)
- `TIMEOUT = 35`.
- Prompt: the two conflict / `needs_review` rules removed; add a rule to set `problem` = the clinical problem the event belongs to, as named in the note (e.g. "community-acquired pneumonia"), free text.
- Returned events always have `needs_review=False`.
- Signature and validation-retry behavior otherwise unchanged.

## Conflict check (new, in core/ — module name implementer's choice)
- Prompt: compare facts across all notes; return only facts whose documented values disagree for the same or an overlapping time period; for each, a short description and one verbatim quote (`span_id` + `quote`) from every conflicting passage. Never resolve.
- Output item: `ConflictItem { conflict_id (placeholder), description, quotes: list[EvidenceRef] (min 2) }`.
- Validation reuses `validate.locate_quote`: unknown span or quote not found → error. One validation retry with errors fed back (same pattern as `extract_events`). After the retry, drop invalid quotes; drop a conflict left with fewer than 2 valid quotes; errors become warnings.
- Zero conflicts is a valid result.
- Own `TIMEOUT = 35`.

## Models (core/models.py)
- `ClinicalEvent.problem: str | None = None`.
- `ConflictItem` as above.

## API streaming (api/streaming.py)
SSE order: any interleaving of `note_extracted` / `note_failed` (one per note, in completion order) → `extraction_done` → `draft` → `done`.
- `note_extracted`: `{document_id, event_count, warnings}`
- `note_failed`: `{document_id, detail}`
- `extraction_done`: `{event_count, warnings, conflict_count}` (existing keys unchanged; `warnings` includes conflict-check warnings and one line per failed note)
- Session `events` = merged, numbered events (set at merge).
- Error path unchanged: conflict-check failure or all notes failing → `error` event, `load_running` cleared.

## Frontend (frontend/src/App.tsx)
- Progress log shows each `note_extracted` as "{document_id}: {n} events" (plus warnings) and each `note_failed` as "{document_id}: failed — {detail}", appearing as the events arrive.
- Step label: "Extracting" until `extraction_done`, then "Drafting", as today.
- Rebuilt `frontend/dist/` committed.

## Seams
- Model boundary: tests stub `core.llm.parse` and dispatch on `schema` (ExtractionResult vs the conflict schema).
- Graph: `load_graph.stream({"documents", "spans"}, stream_mode="updates")` as used by `api/streaming.py`.
- API: TestClient on `POST /api/sessions/{id}/load`.

## Tests
- Fast:
  - one extraction call per document, each seeing only that document's span IDs; plus exactly one conflict-check call seeing all span IDs;
  - extraction calls run concurrently (a stub that blocks until ≥2 calls are in flight completes; a cap of 6 is never exceeded with >6 notes);
  - identical stub output with different completion orders → identical event IDs and order;
  - conflict quote validation: invalid quote dropped, conflict with <2 valid quotes dropped, retry fed errors;
  - conflicts appear as `draft.discrepancies` with the quoted span IDs; events carry `problem`; `needs_review` false;
  - one note failing → load completes with a `note_failed` event and the other notes' events; all notes failing → `error`; conflict-check failing → `error`;
  - SSE sequence per the API section; frontend renders per-note lines as they stream.
- Live (`-m live`): case_001 through the real graph yields D01 (Medication A) via `scripts/coverage.py`; load wall time printed.
- `tests/conftest.py` live fixture and `scripts/coverage.py` run the load graph instead of the single-call extraction.

## Changes to earlier protected tests (allowed)
- `tests/test_extract.py`: timeout assertion 90 → 35; prompt-rule assertions about conflicts, if any.
- `tests/test_api.py`: exact event-sequence assertions become "per-note events, then extraction_done, draft, done".
- Live fixture as above. Assertions otherwise unchanged.
- `tests/test_summarize.py::test_case_001_draft_flags_only_the_medication_conflict` skipped, reason "restored in 07" (user decision). Ticket 07 must unskip it.
- `tests/test_api.py` stub, event counts, call-schema list and `calls.fail` edits made by test-architect are accepted (they follow from per-note calls).

## Clarifications after test design
- All notes failing raises `ExtractionError` (error detail starts with `ExtractionError: `).
- Failed-note and conflict warnings name the document ID / span ID involved.
- The conflict-check validation retry appends the model's output as an assistant message and the errors as a user message, as `extract_events` does.

## Constraints
- No new dependencies. Every model call goes through `core.llm.parse`.
- `core/summarize.py` prompt and signature unchanged (08 replaces it). Review graph, revise, export unchanged.

## Acceptance (functional reviewer)
- Live case_001 load via the API: D01 found; per-note events streamed; wall time recorded twice and compared with the 41–55 s baseline in a comment on ticket 06.

## Out of scope
Pause/resume and resolutions (07); section drafting (08); problem normalization (09); dedupe (10); background retry of failed notes and `note_retrying` (11); RetryPolicy on new nodes (internal retry loops already cover one retry).
