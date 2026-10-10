# 14 implementation contract

Source of truth for ticket 14 (`14-resolution-review.md`). Builds on `07-contract.md` (the conflict pause, the resolution panel, `POST /api/sessions/{id}/resolutions`).

## Requested behavior
When the resident submits the "Resolve conflicts" panel, drafting does not start. A review summary replaces the panel, one row per conflict. **Edit** goes back to the panel with the answers still filled in. **Start drafting** resumes the load. Editing stays locked until `done`, as today.

## User decisions
- **Client-side only.** The API, sessions and graph are unchanged. Start drafting sends today's `POST /resolutions` request with the same body, and its SSE is read as today. Validation errors (422/409) surface only at Start drafting.
- **Pick rows show both** the chosen quote with its marker and the stored text.
- **A failed Start drafting stays on the summary**, with the error shown under it. Edit stays available.
- **Prototype work in the tree** (`main.tsx`, `package.json`, `*Prototype*` files, the rebuilt dist) is stashed (`git stash -u`) for the duration of 14 and popped after the commit.

## Frontend (frontend/src/App.tsx)
- **The panel button** is renamed from "Resolve and continue" to "Review resolutions". Its enabling rule is unchanged: every conflict needs a pick or a non-blank clarification. Clicking it sends no request.
- **Summary** (heading "Review resolutions"). It replaces the panel, which is not shown while reviewing. One row per conflict, in panel order:
  - the conflict ID and description;
  - **chosen:** for a pick, the quote's `marker` and its `quote` (e.g. `[N04:B07] "10 mg daily"`). For a clarification, the label "Clarification" and the trimmed text;
  - **stored as:** `"{description}: {quote}"` for a pick, the trimmed clarification otherwise. This is the same rule as `core/load_graph.py::resolve`. A comment at both sites names the other.
- **Edit** shows the panel again with every pick and clarification kept. Re-submitting shows the summary again.
- **Start drafting** does what `submitResolutions` does today: POST, then on success hide the conflict UI and stream to `done`. It is disabled while the request is in flight.
- **On failure** (non-OK response or network error), the summary stays and shows the error detail. Edit and Start drafting stay enabled.
- **Step label** while the panel or the summary is shown: "Waiting for conflict resolution" (unchanged).
- **A new `conflicts_found`** (a new load) resets to the panel with empty picks, as today.
- Rebuild `frontend/dist/` and commit it.

## Tests (frontend, vitest)
- **Submitting:** the panel button sends no request and shows the summary with one row per conflict.
- **Pick row:** shows the marker, the quote, and `"{description}: {quote}"`.
- **Clarification row:** shows the text trimmed, as both the choice and the stored text.
- **Edit:** returns to the panel with picks and clarifications kept, and resubmitting shows the updated summary.
- **Start drafting:** posts exactly the body today's submit posts, then streams to done and unlocks.
- **Failure:** a 422 on Start drafting keeps the summary and shows the detail. Edit then works.
- **Lock:** ask, corrections, approve and export stay locked while the summary is shown.
- **07 tests:** the 07 frontend tests that click "Resolve and continue" are adapted to "Review resolutions" → "Start drafting". Keep their behavioral assertions and list every edit.
- No Python test changes and no live test. The backend is unchanged. `.venv/bin/pytest -q -p no:warnings` must still pass.

## Constraints
- No new dependencies. No model calls are added.
- No change to `api/` or the request/response shapes. The only change in `core/` is the cross-reference comment in `load_graph.py::resolve`.

## Out of scope
- Restoring the panel or summary after a page refresh.
- Changing resolutions after Start drafting.
- Server-side preview of resolution text.

## Clarifications after test design (user accepted)
- **Names:** buttons "Edit" (exact) and "Start drafting". "Review resolutions" is both the panel button and the summary heading; the panel heading stays "Resolve conflicts".
- **Clarification rows** contain the word "Clarification".
- **Pick rows** do not show the marker of an unchosen quote.
- **Locked** means absent or disabled. While paused there is no snapshot, so the editing controls are not rendered.
- **Test edits accepted:** `App.ticket07.test.tsx` (button lookup renamed, Start drafting click added, the failed-submit test now expects the summary kept).
