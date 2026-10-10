# 04 implementation contract

Source of truth for ticket 04 (`04-review-features-and-lock.md`). Spec: `../spec.md` (stories 21, 22, 38–42, 49; "Editing lock"). Builds on `03a-contract.md` and `03b-contract.md`.

## Requested behavior
Everything the Streamlit app does after a load works in the FastAPI app: a questions chat with conversation memory per session, proposing a correction and accepting or rejecting it, approving the draft, and exporting Markdown. The API refuses these operations with 409 while a load runs. The frontend disables their controls until the `done` event. Logic is reused from `core/review_graph.ask`, `core/revise.propose/accept` and `core/export.to_markdown`. Nothing is reimplemented.

## User decisions
- needs_review badge is in scope (deferred from 03b).
- Discrepancies: read-only list for README demo step 2. Ticket 07 replaces it.
- Export only after approval.

## Backend (api/)
Session store additions (`api/sessions.py`): `revisions: []`, `clarifications: []`, `pending: None` (a `(ProposedRevision, ClinicianClarification)` pair or None). `state()` serializes them as `revisions`, `clarifications`, `pending` (`{"revision", "clarification"}` or null), all JSON via `model_dump(mode="json")`.

`stream_load` also resets `revisions`, `clarifications` and `pending`. Invariant: no correction refers to a draft from an earlier load. `chat_thread_id` is kept across reloads of the same session (03a decision; in the app a session is only reloaded by Retry after a failed load, so the thread is still empty). A new case gets a new session, so its conversation starts fresh.

The order of checks is the same for every operation below:
1. Unknown session → 404.
2. `load_running` true → 409 `{"detail": "load running"}`.
3. `draft` is None (never loaded, or the load failed) → 409 `{"detail": "no draft"}`.
4. The operation-specific checks.

| Operation | Request | Success | Operation-specific failures |
|---|---|---|---|
| Ask | `POST /api/sessions/{id}/ask` `{question}` | 200 `{intent, answer, cited}` (`cited` = span IDs). Calls `ask(question, draft, spans, events, thread_id=chat_thread_id)` | Blank question → 422. Exception from `ask` → 502 `{"detail": "<Type>: <msg>"}` |
| Propose | `POST /api/sessions/{id}/corrections` `{claim_id, after, statement}` | 201 `{revision, clarification}`. Numbering `n = len(revisions) + 1`. Stored as `pending`; the draft does not change | Unknown claim_id → 404. A correction already pending → 409 |
| Accept | `POST /api/sessions/{id}/corrections/{revision_id}/accept` | 200, body = `GET /api/sessions/{id}`. Draft = `accept(draft, rev)` (text updated, clarification linked, status reset to draft). Revision and clarification are appended with status `accepted`; `pending` cleared | revision_id is not the pending one → 404 |
| Reject | `.../reject` | 200, same body. Draft unchanged. Both appended with status `rejected`; `pending` cleared | same as accept |
| Approve | `POST /api/sessions/{id}/approve` `{reviewer}` | 200, same body. Draft `status="approved"`, `approved_at=now`, `reviewer` | A correction is pending → 409. Blank reviewer → 422 |
| Export | `GET /api/sessions/{id}/export` | 200 `text/markdown`, `Content-Disposition: attachment; filename="discharge_summary_{case_id}.md"`. Body = `to_markdown(draft, spans, documents, case_id=case_id, clarifications=clarifications)` | Draft not approved → 409 |

Request models go in `api/schemas.py`.

## Frontend (frontend/src/App.tsx, may split into sibling modules)
- **Lock:** a `ready` flag is true only after the `done` event of the current load. Until then every control below is disabled: the Ask input and button, the correction form and Propose, Accept, Reject, the reviewer input and Approve, and Export. A new Load or a Retry sets `ready` false again.
- **Status line:** "Draft — pending review", or "Approved by {reviewer} at {YYYY-MM-DD HH:MM}".
- **Claim badges:** `needs_review` without clarifications gets an orange "needs review" badge. `needs_review` with ≥1 `clinician_clarification_ids` gets a green "clarified by clinician — pending approval" badge. Each clarification also shows `Clinician-provided ({id}): "{statement}"` under its claim (statement from the session's `clarifications`).
- **Discrepancies:** read-only list of `draft.discrepancies`: id, status, description, and each source passage (marker, filename, text) side by side.
- **Chat:** question input and Ask button. History shows question, answer, and citation markers (same popover as claims) for `cited`. A failed ask shows "Question failed: {detail}" in the chat and keeps the earlier history. A new Load clears the history.
- **Correction:** a claim select (defaults to the first needs_review claim, else the first claim), a clinician statement input, and a corrected-text textarea prefilled with the selected claim's text. Propose shows the pending revision: Before (struck through), After, the statement, and Accept and Reject buttons. While a correction is pending, the form is hidden. Accept and Reject refresh the draft from the response. A list of resolved revisions shows "{R01} → {C11}: accepted".
- **Approve:** reviewer input defaults to "Simulated resident (demo)". Approve is disabled while a correction is pending, with the note "Accept or reject the pending correction before approving."
- **Export:** button enabled only when the draft is approved. It fetches the export endpoint and downloads the body as `discharge_summary_{case_id}.md` (Blob + anchor).
- Layout: a single page, no tabs (planner default). Flowbite defaults.

## Seams
- `frontend/src/App.tsx` default export `App` stays the only module tests import.
- Backend tests stub the model at `core.llm.parse` (existing `calls` fixture), or monkeypatch `api` module's `ask` reference if simpler. test-architect picks one and states which.

## Tests
- Backend (pytest, TestClient): every operation's success path; 409 for each of the 6 operations while `load_running`; 409 with no draft; 404 unknown session; ask uses the session's `chat_thread_id` and two sessions use different ones; ask failure → 502; propose leaves the draft unchanged; accept updates the text, links the clarification, and resets an approved draft to draft; reject leaves the draft unchanged; second propose while pending → 409; approve while pending → 409; export before approval → 409; export after approval contains the synthetic label, "APPROVED by", the discrepancies section, the accepted clarification, and "Source appendix"; a new load clears pending/revisions/clarifications (and keeps `chat_thread_id`, as 03a tests already assert).
- Frontend (vitest, `fetch` stubbed): controls disabled after the `draft` event and before `done`, enabled after `done`; ask renders the answer with markers; ask failure shows "Question failed"; propose shows the before/after diff; accept updates the claim text and shows the green badge and the clinician-provided line; reject leaves the text unchanged; Approve is disabled while a correction is pending; Export is disabled until approved and calls the export URL after approval; orange badge on a needs_review claim; discrepancy list renders.

## Changes to earlier protected tests (user-approved)
- `frontend/src/App.test.tsx`: the case picker is located with `getByRole("combobox", { name: /case/i })` instead of an unnamed combobox (the claim select is a second combobox). Locator only, assertions unchanged.

## Constraints
- No new dependencies. Rebuilt `frontend/dist/` committed with the change.
- `app.py` (Streamlit) and `core/*` are unchanged. README unchanged (rewrite is ticket 05).
- Acceptance "demo script runs end to end": the functional reviewer walks README steps 1–7 in the new app (live model if the key is available, otherwise stubbed), with step names mapped to sections of the single page.

## Out of scope
Conflict resolution panel and resolutions (07); per-note/per-section events (06, 08); Streamlit retirement and README rewrite (05); Sources tab (the full passage list; citation popovers already cover it); persistence; tabs and visual polish.
