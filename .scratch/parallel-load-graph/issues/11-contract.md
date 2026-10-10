# 11 implementation contract

Source of truth for ticket 11 (`11-failed-note-retry.md`). Spec: `../spec.md` (stories 6–10; "Failed note"). Builds on `10-contract.md`, `09-contract.md`, `08-contract.md`, `06-contract.md`.

## Requested behavior
If a note's extraction still fails after its internal validation retry, the load continues without it and the resident is told. This is already the case since 06. After the first draft has been streamed, each failed note is retried. When a retry succeeds:
- the note's events are merged in;
- the sections whose input changed are redrafted;
- dedupe reruns;
- a new draft snapshot streams.

When a retry finally fails, the resident is told that the draft is missing that note, and the export says so too. `done`, and with it the unlock, is sent only after every retry has settled.

## Planner decisions (user delegated all open questions)
- **When retries run:** after the first `draft` (join + dedupe), inside the load graph.
  - LangGraph runs supersteps in lockstep, so a retry branch running alongside extraction would hold back merge and the conflict pause.
  - Running it after the first draft lets the resident read the draft while retries run. Editing stays locked anyway.
  - With conflicts, retries run after the resume's first draft.
- **Attempts:** up to `RETRY_ATTEMPTS = 2` per failed note. Each attempt is one `core.extract.extract_events` call, which keeps its own validation retry, preceded by a `RETRY_DELAY = 2` s sleep.
  - Both values are module constants in `core/load_graph.py`; tests monkeypatch them and the sleep.
  - Failed notes are retried concurrently, one `Send` per note.
- **No failed notes:** the graph ends after the first `draft`, exactly as today. Nothing is added to the stream.
- **After all retries settle**, one redraft step runs:
  - **Events:**
    - The successful notes' events are merged with the existing ones using the existing deterministic merge order (document, then passage).
    - Event IDs are renumbered E01… over the whole set.
    - Events that overlap a conflict quote are excluded from drafting, as before.
  - **Problems for the new events:**
    - One normalization call maps the new raw labels onto the existing canonical problems, which are passed in as already canonical. It can also create new problems.
    - Existing problems are never renamed or merged.
    - Null labels go to `Other`.
    - If the call fails, raw labels are used; a raw label that matches an existing problem case-insensitively joins it.
    - Problem order is recomputed using the 09 rule.
  - **Which sections are affected:** a section is redrafted only when its input changed.
    - Hospital course: only the problem groups that gained a non-conflicting event.
    - Other sections: these receive all events, so all of them are redrafted when any non-conflicting event was added.
    - If nothing changed, nothing is redrafted.
  - **Redraft:**
    - Affected sections are drafted with the existing per-section and per-problem calls, run concurrently.
    - The join uses the latest record for each (section, problem) group. Unaffected groups keep their previous section records unchanged.
    - Then dedupe reruns over the whole draft, and the claims are renumbered C01….
    - Resolutions and their fallback behave as in 07–10.
  - **Section failure during the redraft:** the load fails, as in 08. This is consistent with the rest of drafting.
  - **Final failure:**
    - The note is added to `missing_notes`.
    - A warning `"{document_id}: extraction failed after retries — the draft is missing this note"` is added to the draft warnings.
    - The load still ends with `done`.
- **Retries happen only once per load.** A redraft never triggers more retries.

## API / SSE (api/streaming.py)
- **Unchanged:** the first-pass events (`note_failed {document_id, detail}` on the first failure, then sections, `dedupe_applied`, `draft`).
- **After the first `draft`,** one `note_retrying {document_id}` per failed note, in document order.
- **When each note's retry settles:**
  - on success: `note_extracted {document_id, event_count, warnings}` (the same shape as in the first pass);
  - on final failure: `note_failed {document_id, detail}` (the same shape).
- **If anything was redrafted:** the `section_drafted` / `section_omitted` events for the affected sections, then `dedupe_applied`, then `draft` (the full new snapshot, with warnings), then `done`.
- **If nothing was redrafted:** if any note finally failed, the stream sends a `draft` snapshot that includes the missing-note warning before `done`. Otherwise it goes straight to `done`.
- **Session:**
  - gains `missing_notes: list[str]`, reset by a new load;
  - `events` reflects the merged set;
  - `draft` is the latest snapshot;
  - `load_running` stays true until `done`/`error`, so editing stays locked while retries run.

## Export (core/export.py)
- When `missing_notes` is non-empty, a line `**Incomplete: notes not included (extraction failed): note_02, …**` goes right after the status lines. The export endpoint passes the session's `missing_notes`.

## Frontend (frontend/src/App.tsx)
- **Progress log:**
  - `note_retrying` reads "{document_id}: retrying".
  - A `note_failed` that follows a `note_retrying` for the same note reads "{document_id}: failed after retries — draft is missing this note".
- **Step label:** "Retrying failed notes" while a `note_retrying` is unsettled and `done` has not arrived.
- **Missing-note alert:** once `done` arrives, a warning alert lists the missing notes. Its source is the session snapshot's `missing_notes`, or the log if that is simpler; either way the visible text names each note.
- **Final draft view:** each later `draft` event refreshes it.
- Rebuilt `frontend/dist/` committed.

## Seams
- Model: stub `core.llm.parse`, making a chosen note's extraction raise or fail a chosen number of times.
- Graph: `load_graph.stream`.
- API: TestClient.

## Tests
- Fast:
  - **No failed notes:** the stream and the calls are unchanged.
  - **Successful retry:**
    - `note_failed` → first `draft` → `note_retrying` → `note_extracted` → section events only for affected groups → `dedupe_applied` → `draft` → `done`;
    - the new snapshot contains claims built from the note's events;
    - unaffected hospital-course problem groups get no new section call;
    - dedupe is called again;
    - claims are renumbered contiguously.
  - **Retry with nothing to redraft:** when the note's events all overlap conflicts, no section call is made.
  - **Final failure:**
    - exactly `RETRY_ATTEMPTS` retry attempts;
    - `note_failed` again;
    - a `draft` carrying the missing-note warning;
    - `done`;
    - `missing_notes` in the session and in the export.
  - **Problems for new events:** a new label that matches an existing problem joins it, and existing problem names are unchanged.
  - **Editing lock:** editing endpoints return 409 after the first `draft` until `done`.
  - **Two failed notes** are retried concurrently, followed by one redraft and one dedupe.
  - **Load with conflicts:** retries run after the resume's first draft.
  - **New load:** resets `missing_notes`.
  - **Frontend:**
    - the `note_retrying` log entry and the final-failure wording;
    - the step label while retrying;
    - the missing-note alert after `done`;
    - the second `draft` refreshes the view.
- Live: none. A real failure can't be reproduced on demand, so the fast tests cover the behavior.

## Constraints
- No new dependencies. Every model call goes through `core.llm.parse`.
- Earlier tests may be adapted only where the new behavior requires it (for example, 06 `test_one_note_failing_does_not_fail_the_load` now sees retries). Their behavioral assertions stay.

## Out of scope
- Retrying the conflict check.
- Retrying across loads or app restarts.
- Persistent checkpoints.
- Manual "retry note" buttons.
- LangGraph `RetryPolicy` for API exceptions (spec "one retry layer"), which belongs to a separate ticket.

## Clarifications after test design (planner)
- **Test-imposed interfaces (accepted):**
  - The retry delay calls `time.sleep(RETRY_DELAY)`, through the `time` module or a module-level `sleep` in `core.load_graph`.
  - `RETRY_ATTEMPTS` and `RETRY_DELAY` are read at run time.
  - The retry normalization call is recognized by its 09 schema. The existing canonical problems (excluding `Other`) are passed as `Problem: <name>` lines, and the new raw labels appear in the messages.
  - The missing-note alert has `role="alert"`.
- **One attempt** is one `extract_events` call. The model is called twice when the first call raises.
- **Stream order after the first draft:**
  - All `note_retrying` events come first, in document order.
  - Settle events (`note_extracted` / `note_failed`) can arrive in any order.
  - Every settle event comes before any redraft event.
- **Nothing redrafted and no final failure:** neither `dedupe_applied` nor `draft` is sent before `done`.
- **Redraft failure:** sends `error`. `load_running` becomes false. The session `draft` is cleared to None, so the resident cannot edit or export a draft whose load failed; Retry reruns the load. This is consistent with 08.
- **`missing_notes`** and the export "Incomplete" list are in document order, joined with ", ". The line is the first non-empty line after `- Generated: …`.
- **Accepted test edit:** the 06 test edit (`test_one_note_failing_does_not_fail_the_load` now sees retries).
