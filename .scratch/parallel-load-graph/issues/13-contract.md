# 13 implementation contract

Source of truth for ticket 13 (`13-model-proposed-corrections.md`). Spec story 40. Builds on ticket 04 (`04-contract.md`, the correction flow and the editing lock).

## Requested behavior
`POST /api/sessions/{id}/corrections` takes `{claim_id, statement}`. Code makes one model call through `core.llm.parse`. The call gets:
- the claim's section and text;
- the full text of each passage the claim cites (span ID and text);
- the clinician's statement.

It returns `{after}`, the rewritten claim text. That text becomes the pending `ProposedRevision.after`, and the response shape is unchanged. Accept and reject are unchanged.

## Planner decisions (user chose option B; the remaining details were delegated)
- **Prompt rules:**
  - Change only what the statement corrects, and keep the rest of the claim's wording.
  - Use no fact that is in neither the statement nor the cited passages.
  - Keep the result to one or two sentences, with no commentary.
  - The statement is clinician-provided and takes precedence over the passages where they disagree.
- **Schema:** `CorrectionResult { after: str }`. Timeout 20 s.
- **Retries:** one retry on an exception, or when `after` is blank or identical to the current text (whitespace-trimmed). For the retry, the error is fed back as in the other retry loops.
- **Failure responses:** no pending correction is created in either case.
  - Both attempts raise: HTTP 502 `{"detail": "correction failed: …"}`.
  - The result is still blank or unchanged after the retry: HTTP 422 `{"detail": "the statement did not change the claim"}`.
- **Validation (unchanged codes):**
  - 404 unknown session or claim;
  - 409 load running, no draft, or a correction already pending;
  - 422 blank statement, as a new check.
- **Locking:**
  - Do not hold `sessions.lock` during the model call.
  - Validate under the lock, release it, call the model, then re-acquire the lock and re-check. If a load started, the draft object changed, or a correction became pending meanwhile, return 409 and discard the result.
- **Request body:** `after` is no longer accepted. `Propose` becomes `{claim_id, statement}`.
- **Accepting:** the clinician cannot edit the proposed text before accepting. To change it, they reject and state the correction again. This keeps who wrote what unambiguous.
- **Provenance:** unchanged. A `ClinicianClarification` holds the statement, the revision keeps the claim's `source_span_ids`, and accept links the clarification and resets approval.

## Frontend (frontend/src/App.tsx)
- **"Correct a claim" panel:**
  - a Claim select;
  - a "What should it say?" statement input (aria-label "Clinician statement");
  - a **Propose correction** button, disabled while the statement is blank or a proposal is in flight. The "Corrected text" textarea is removed.
- **While proposing:** the button shows "Proposing…".
- **On error:** the error detail is shown under the panel, and the inputs keep their values.
- **Pending view:** unchanged. It shows the claim ID, Before (struck through), After, the clinician statement, and Accept/Reject.
- **Build:** rebuild `frontend/dist/` and commit it.

## README
Demo step 5 now reads: pick a claim → type what should change → **Propose correction** → review the proposed text → **Accept** or **Reject**. Remove the 5 mg → 10 mg example; conflicts are resolved before drafting, since ticket 07.

## Tests
- Fast:
  - **The model call:**
    - makes one `llm.parse` call whose messages contain the statement, the claim text and each cited passage's text;
    - no passage the claim doesn't cite reaches the call;
    - the call's result becomes `revision.after`.
  - **Retries and failures:**
    - a blank or unchanged result, or an exception, is retried once with the error fed back;
    - still unchanged → 422;
    - two exceptions → 502;
    - neither creates a pending correction, and a later propose works.
  - **Validation:** blank statement → 422 with no model call; unknown claim → 404; 409 cases as before.
  - **Accept/reject:** behave as in 04 (text applied, clarification linked, approval reset, export shows the clinician-provided line).
  - **Lock not held:** while the model call is in flight, another session's GET returns, and a load started on the same session makes the proposal end in 409.
  - **Frontend:**
    - there is no Corrected text field;
    - Propose is disabled until a statement is typed;
    - the proposed After is shown with Accept/Reject;
    - an error keeps the inputs.
- Live (`-m live`): on case_001, propose a correction to a `follow_up` claim with the statement "Follow-up with the primary care clinic within 7 days of discharge." Check that `after` differs from `before` and contains "7 days", and that accepting it updates the claim.

## Constraints
- No new dependencies. Every model call goes through `core.llm.parse`.
- Earlier tests that post `after` (ticket 04 API and frontend tests) may be adapted to the new request and a stubbed proposal. Keep their behavioral assertions and list every edit.

## Out of scope
Speech input, editing the proposal before accepting, multi-claim corrections, and corrections that add new claims.

## Clarifications after test design (planner)
- **A posted `after` field** is rejected with 422. `Propose` forbids extra fields, so clients that still send it fail visibly instead of being silently ignored.
- **Retries:** there is one retry, whatever the first failure was. The second attempt alone sets the response: an exception gives 502, and a blank or unchanged result gives 422.
- **Retry messages after a blank or unchanged result:** the retry resends the first call's messages and appends the result plus the error. After an exception, it resends the same messages.
- **Interfaces imposed by the tests (accepted):**
  - The correction schema has an `after` field.
  - The call is `llm.parse(schema, messages, 20)`.
  - The statement, the claim text and section, and each cited span ID and passage text appear verbatim in the messages. No uncited span ID or passage text appears.
  - Error details:
    - a 502 detail starts with `correction failed: `;
    - the 422 detail is exactly `the statement did not change the claim`.
  - Frontend:
    - the statement input is labelled "Clinician statement";
    - the button reads "Proposing…" while in flight;
    - there is no textarea;
    - the Before text is struck through.
- **Test edits accepted:** the edits to `test_api_ticket04.py`, `test_api_ticket04_review.py` and `App.ticket04.test.tsx`.
