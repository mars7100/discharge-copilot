# 10 implementation contract

Source of truth for ticket 10 (`10-dedupe.md`). Spec: `../spec.md` (stories 35, 36, 48; "Dedupe"). Builds on `09-contract.md`, `08-contract.md`.

## Requested behavior
After the sections join, one dedupe call reads all claims and returns only the IDs of claims to drop because they repeat a fact stated in another claim. The output schema is built at runtime, so a drop ID can only be one of the existing claim IDs. Code applies the drops, with guards. The remaining claims are renumbered C01… in the same template, problem and model order. The stream reports how many claims were removed. Apart from the removed claims and the renumbering, the draft is unchanged.

## Planner decisions (user delegated all open questions)
- **Placement:** `… draft_section × N → draft (join) → dedupe → END`.
- **Skipped call:** no call is made when the joined draft has fewer than 2 claims.
- **Schema:**
  - Runtime pydantic model, `drop_claim_ids: list[Literal[<existing claim IDs>]]`. It is built per call with `create_model` and has no free-text fields.
  - If the IDs are missing, duplicated or unknown in any way, code ignores them: it filters to known IDs and removes repeats.
- **Prompt input:** one line per claim, `C01 | section | problem | text`.
- **Prompt rules:**
  - Drop a claim only when another claim states the same fact.
  - Of each duplicate group, keep the one in the section where the fact belongs best. For example, a discharge medication stays in `discharge_medications`, and a test result stays in `key_events`. Never drop claims that are related but say different things.
  - An empty list is a valid answer.
- **Guards** run in drop-list order, and a refused drop adds a warning naming the claim and the reason:
  - **Resolution guard:** a drop is refused if it would remove the last remaining claim carrying a given resolution ID (`clinician_clarification_ids`).
  - **Section guard:** a drop is refused if it would leave a section, or a hospital-course problem group, with no claims. Otherwise a required section would falsely read "Not documented in the supplied notes." and an optional one would vanish.
- **Renumbering:**
  - The claims left are renumbered C01… contiguously in their existing order.
  - Claim IDs are only visible after the final `draft` snapshot, as decided in 08, so renumbering is invisible to the resident.
- **Failure:** one retry. If both attempts raise, all claims are kept, a warning is added and the load continues. Dedupe is cleanup, not a safety gate, so it never fails the load.
- **Timeout:** 35 s, the same as the section calls.

## Graph / summarize
- The dedupe logic, made up of the call, the guards and the renumbering, lives in `core/summarize.py` or a new small module. It takes the joined draft and returns the deduped draft, the removed claims and warnings.
- The join no longer produces the final `draft` state on its own. The dedupe node writes `draft`, plus `draft_warnings` extended with dedupe warnings.

## API / SSE (api/streaming.py)
- After the section events: `dedupe_applied {count, removed: [{section, problem, text}]}`, then the single final `draft` snapshot, then `done`. This order applies on both load and resume.
- `dedupe_applied` is sent even when count is 0, including when the call was skipped.
- The session's `draft` is set only from the final, deduped snapshot.

## Frontend (frontend/src/App.tsx)
- The progress log has an entry for `dedupe_applied` that reads "{count} duplicate claims removed", with one sub-line per removed claim (`section: text`).
- No other UI change. Rebuild `frontend/dist/` and commit it.

## Seams
- Model: stub `core.llm.parse`. The dedupe call is identified by a schema with a `drop_claim_ids` field.
- Graph: `load_graph.stream`.
- API: TestClient.

## Tests
- Fast:
  - the dedupe schema's item type is an enum of exactly the joined claim IDs, so a stubbed out-of-set ID fails schema validation or is ignored and never removes anything;
  - listed claims are removed and the rest are renumbered contiguously in order;
  - the resolution guard keeps the last resolution-carrying claim and warns, but a duplicate resolution-carrying claim can still be dropped when another carrier remains;
  - the section guard keeps the last claim of a section or problem group and warns;
  - `dedupe_applied` comes after the section events and before `draft`, with the right count and removed texts, on load and resume;
  - count 0, with no call made, for drafts with fewer than 2 claims;
  - a dedupe failure on both attempts keeps all claims, adds a warning and the load reaches `done`;
  - with an empty drop list, the draft equals the joined draft;
  - frontend: the `dedupe_applied` log entry renders the count and the removed texts.
- Live (`-m live`):
  - a real `llm.parse` call with the runtime dedupe schema over a case_001 draft succeeds (the API accepts the enum schema), and every returned ID is in the claim set;
  - the case_001 load still has discharge diagnoses, follow-up, the pneumonia and hypertension groups, and the D01 resolution claim.

## Constraints
- No new dependencies. Every model call goes through `core.llm.parse`.
- Earlier tests that stub model calls may be adapted to answer the dedupe call (default: empty drop list) and to expect `dedupe_applied` in streams. Their behavioral assertions stay.

## Out of scope
- Background note retry and rerunning dedupe after a retry (11).
- Merging duplicate claims' citations.
- Letting the resident undo a drop.

## Clarifications after test design (planner)
- **Accepted test-imposed interfaces:**
  - the dedupe call is recognized by a schema with a `drop_claim_ids` field, which must be its only property;
  - the items' JSON schema carries `enum`;
  - `model_validate` rejects unknown IDs, and code still handles out-of-set IDs coming from `model_construct`;
  - the `dedupe_applied` payload keys are exactly `count` and `removed[{section, problem, text}]`.
- **Refusal warnings** go into `draft_warnings`. Each one names the claim by its pre-dedupe ID or its text. A resolution-guard warning also names the resolution ID.
- **Unknown or repeated IDs** are ignored silently. They add no warning.
- **`removed`** is listed in claim order.
- **Accepted test edits:** the stub and order edits to `tests/section_stub.py`, `tests/test_api.py`, the 06/07/08/09 tests, and the spy in the `case001` fixture in `tests/conftest.py`.
- Planner resolved TEST_CONTRACT_CONFLICT: `test_ticket06_parallel_load.py::test_conflicts_become_discrepancies_and_sse_reports_each_note` adapted to expect `dedupe_applied` before `draft` on resume (missed in test design).
- Join and dedupe are one graph node named `draft` (earlier protected tests expect exactly one `Draft` update from the node `draft`). Accepted.
