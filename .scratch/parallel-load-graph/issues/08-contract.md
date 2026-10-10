# 08 implementation contract

Source of truth for ticket 08 (`08-section-drafting.md`). Spec: `../spec.md` (stories 20–22, 27–33, 37; "Phase 2 nodes", "Claims and IDs"). Builds on `07-contract.md`, `06-contract.md`, ticket 02 (`core/template.json`).

## Requested behavior
After resolution, every section in `core/template.json` is drafted in its own model call, all at once (`max_concurrency=6` stays). Each call returns `{documented, claims}` for its section. Code omits an optional section with `documented: false`. A required section with `documented: false` gets no claims and shows "Not documented in the supplied notes." (existing rendering). `documented: true` with no valid claims logs a warning. After the join, claims are numbered C01… in template order, keeping model order within each section. As each section finishes, the stream sends it and the frontend renders it. Editing stays locked until `done`.

## User decisions
- **Resolutions:** every section call gets all resolutions. After the join, a resolution that no claim carries is appended by code to `hospital_course` as a claim, with a warning and no extra model call (the 07 fallback claim). The 07 cross-call retry for a missing resolution is removed.
- **Section failure:** a section call that still fails after its one retry, from an exception or from having no valid claims while `documented: true`, fails the load. This is the same behavior as a draft failure today: `error` event, flags cleared, Retry reruns the load.
- **Early display:** streamed section claims are shown as text plus citation markers, with no claim IDs or claim controls. IDs, badges and controls appear once the final `draft` snapshot arrives.
- **Inputs:** every section call gets the same input as today's draft call: all non-conflicting events plus the resolutions.

## Graph (core/load_graph.py)
`… resolve → [draft_section × N via Send] → join → END`
- **draft_section**: one `Send` per template section. It returns that section's claims (placeholder IDs), `documented`, and warnings. Completion order must not affect the result.
- **join**: orders sections by template order, numbers the claims C01…, applies the resolution post-processing (all quote spans added, `needs_review`, missing-resolution fallback), and attaches discrepancies. It returns `draft` and `draft_warnings` as the `draft` node does today.
- A conflict-free load goes straight to drafting, as before.

## Drafting (core/summarize.py)
- Per-section function: input is a section ID, events, spans and resolutions. It returns `{documented, claims, warnings}`.
- Structured output: `documented: bool`, `claims`. Claims must be in that section. A claim in a different section is a validation error.
- Per-call validation retry (one retry): unknown span IDs, unknown `clinician_clarification_ids`, and claims in the wrong section. The "resolution not carried" check moves to the join.
- The prompt tells the call the section's purpose. It also tells the call to set `documented: false` when the events state nothing for that section, and to include only the facts that belong there. The section list and wording otherwise come from `TEMPLATE`.
- `check_claims` is unchanged and still used.

## API / SSE (api/streaming.py)
- New events, sent in completion order while drafting runs:
  - `section_drafted {section_id, claims: [{section, text, evidence_span_ids}], warnings}`
  - `section_omitted {section_id}`: optional sections with `documented: false` only.
- Then `draft` (the final snapshot, unchanged shape) and `done`. Load and resume both stream these.
- No change to the editing lock: `load_running` stays true until `done`/`error`.

## Frontend (frontend/src/App.tsx)
- While drafting: sections appear in template order as their `section_drafted` arrives. Each shows claim text and citation markers (popovers work), with no claim IDs, badges or controls. `section_omitted` sections stay hidden. The progress log has one entry per `section_drafted` / `section_omitted`.
- The final `draft` snapshot replaces the early view with the existing full render.
- Rebuilt `frontend/dist/` committed.

## Seams
- Model: stub `core.llm.parse`, keyed on schema and section (as the 06/07 tests do).
- Graph: `load_graph.stream(..., stream_mode="updates")`.
- API: TestClient on the load and resolutions endpoints.

## Tests
- Fast:
  - one draft call per template section, run concurrently, and only after resolution;
  - optional + `documented: false` → `section_omitted`, absent from draft and export; required + `documented: false` → no claims, "Not documented in the supplied notes." in export/frontend; `documented: true` + no claims → warning;
  - numbering C01… in template order is identical for different completion orders;
  - a citation error in one section → that section is retried with the error, and other sections are not re-called;
  - resolution carried by a claim → all quote spans + `needs_review` (07 behavior); carried by no section → appended `hospital_course` claim + warning, with no extra model call;
  - a section failing after its retry → `error`, flags cleared;
  - SSE order: `section_drafted`/`section_omitted` events before `draft`, then `done`;
  - frontend: streamed sections render text + markers without IDs/controls; controls stay locked until `done`.
- Live (`-m live`): the case_001 draft has `discharge_diagnoses` and `follow_up` claims, every claim cites passages, and the Medication A resolution is carried with both quote spans.

## Constraints
- No new dependencies. Every model call goes through `core.llm.parse`.
- The review graph, revise, export format and resolution API are unchanged.
- Tests from earlier tickets that stub the single `SummaryResult` call or test `generate_draft`'s cross-call resolution retry (`test_ticket07_resolve_conflicts.py::test_draft_missing_a_resolution_is_retried_then_appended_with_a_warning`, 06/07/API stubs) may be adapted to the per-section shape. Their assertions on behavior stay, except the retry count that the user decision above removes.

## Out of scope
Hospital course per problem and problem normalization (09); dedupe, so a fact may appear in several sections in 08 (10); background note retry (11); per-section event filtering.

## Clarifications after test design
- `documented: true` with an empty claims list → warning, load continues. Claims returned but none valid after the one retry → load fails.
- The fallback claim for an uncarried resolution goes last within `hospital_course`; all claims are then numbered C01… in template order.
- Each section call's messages name exactly one template `section_id` (its own) before any retry turn; the prompt must not list other section IDs. The per-section output schema has `documented` and `claims` (SummaryClaim fields).
- Test edits test-architect made to `tests/test_api.py`, `tests/test_ticket06_parallel_load.py`, `tests/test_ticket07_resolve_conflicts.py` and the new `tests/section_stub.py` are accepted. `test_api_ticket04*.py` failures come from the shared per-section stub and must pass once 08 is implemented.
