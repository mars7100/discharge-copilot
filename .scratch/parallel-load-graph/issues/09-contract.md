# 09 implementation contract

Source of truth for ticket 09 (`09-hospital-course-by-problem.md`). Spec: `../spec.md` (stories 23–25; "Phase 1 nodes" problem-normalization, "Phase 2 nodes" problem grouping). Builds on `08-contract.md`, `07-contract.md`.

## Requested behavior
After merge, one problem-normalization call maps the per-note `problem` labels onto one canonical problem list (so "CAP" and "community-acquired pneumonia" become one problem). Every event ends up with exactly one canonical problem. The hospital course is drafted with one call per canonical problem, all at once, alongside the other sections. Each call is condensed to the events that changed the stay. The hospital course is shown and exported grouped by problem, under problem subheadings.

## Planner decisions (user delegated all open questions)
- **Placement:** `merge → normalize → resolve`. Normalization runs before the conflict pause, so its latency is hidden behind extraction and resolution.
- **Input to the call:** the distinct non-null raw labels, plus one line per conflict (`D01 | description | quotes`) so that each conflict, and with it its resolution, is assigned to a problem.
- **Output:** a canonical problem list, each problem with the raw labels and conflict IDs it covers.
- **Coverage, guaranteed by code:**
  - Events with a null problem, and conflicts the call does not map, go to a canonical problem named `Other`.
  - A raw label the call does not map becomes its own canonical problem.
  - A label or conflict mapped twice takes its first mapping.
  - Unknown labels and IDs in the output are ignored.
  - Each code fix adds a warning to `extract_warnings`.
- **Failure:** one retry, then fall back to raw labels: each distinct label is its own problem, null labels and all conflicts go to `Other`, and a warning is added. Normalization never fails the load, because grouping is presentation and not a safety gate.
- **Storage:** normalization rewrites each event's `problem` to its canonical name. The raw label is not kept.
- **Problem order:** by first appearance in the merged event order (E01…). `Other` always comes last. The order must not depend on the model's list order or on completion order, so numbering stays stable.
- **Hospital-course calls:**
  - One call per canonical problem. Each gets only that problem's non-conflicting events and only the resolutions of the conflicts mapped to that problem.
  - A problem with neither events nor resolutions gets no call.
  - The prompt names the section (`hospital_course`) and the problem, and asks for chronological claims limited to events that changed the course of the stay.
  - Per-call validation and retry are as in 08.
  - A per-problem `documented: false` gives that problem no claims, and its group is not shown.
- **Other sections:** unchanged from 08. They get all non-conflicting events and all resolutions.
- **Claims:** `SummaryClaim` gains `problem: str | None = None`. Code sets it to the call's canonical problem on hospital_course claims, and to None elsewhere. The model never decides it.
- **Uncarried resolution fallback:** the code-added claim goes last within its mapped problem's hospital_course group, with `problem` set to that problem.
- **Numbering:** C01… in template order. Within hospital_course, claims follow problem order, then model order.
- **Failure:** a per-problem call that fails after its retry fails the load, as for any section in 08.

## Graph (core/load_graph.py)
- New `normalize` node between merge and resolve. It updates `events` with the canonical problems, and keeps the conflict→problem mapping and the problem order in state.
- `fan_out_sections` sends one `draft_section` per non-hospital-course template section, plus one per hospital-course problem. The join assembles them in template order and then problem order.

## API / SSE (api/streaming.py)
- The session's `events` reflect the canonical problems once normalization is done.
- `section_drafted` for hospital_course is sent once per problem call and gains `problem: str`. Other sections are sent as in 08, with `problem: null`. A hospital_course call with `documented: false` sends `section_drafted` with empty claims. No `section_omitted` is sent for hospital_course, because it is required.
- The final `draft` snapshot claims carry `problem`.

## Frontend (frontend/src/App.tsx)
- Hospital course is rendered with one subheading per problem, in claim order, in both the early streamed view and the final view.
- Empty problem groups are not shown. If no group has claims, the existing "Not documented in the supplied notes." is shown.
- Rebuilt `frontend/dist/` committed.

## Export (core/export.py)
- Under `## Hospital course`, each problem gets a `### {problem}` subheading in claim order, followed by its claims.
- Claims with no problem (for example, corrections added later) go under no subheading at the top.
- Other sections are unchanged.

## Seams
- Model: stub `core.llm.parse`. Normalization is identified by its schema.
- Graph: `load_graph.stream`.
- API: TestClient.

## Tests
- Fast:
  - normalization merges synonym labels; null-label events and unmapped conflicts go to `Other`; unmapped labels become their own problem; a normalization failure falls back to raw labels with a warning and the load still completes;
  - one hospital_course call per problem, run concurrently; each call gets only its problem's events and its mapped resolutions;
  - claims carry `problem`; numbering follows template order, then problem order (`Other` last), and is identical for different completion orders;
  - the uncarried-resolution fallback lands in its mapped problem group;
  - `section_drafted` carries `problem`;
  - export renders `### {problem}` subheadings;
  - frontend renders problem subheadings in the early and final views.
- Live (`-m live`): the case_001 hospital course has a problem group whose name contains "pneumonia" and one containing "hypertension" (case-insensitive).

## Constraints
- No new dependencies. Every model call goes through `core.llm.parse`.
- Earlier tests that stub drafting calls may be adapted to the per-problem shape, keeping their behavioral assertions.
- The 08 test-imposed prompt rule holds: each section call's messages name exactly one template section_id.

## Out of scope
- Dedupe (10).
- Background note retry (11).
- Editing or renaming problems in the UI.
- Terminology standards.

## Clarifications after test design (planner)
- Null-label events going to `Other` is expected behavior, not a code fix, so it adds no warning. Warnings are for unmapped labels, labels or conflicts mapped twice, unmapped conflicts and the fallback.
- No normalization call is made when there are no raw labels and no conflicts. Everything goes to `Other`.
- A problem that has only a resolution and no events is ordered after the problems that have events and before `Other`, in conflict-ID order.
- Normalization failure means an exception from `llm.parse` on both attempts.
- Test-imposed interfaces from test-architect are accepted:
  - the normalization schema has a top-level list of items, each with one `str` name, a raw-labels list and a conflict-IDs list (the field name contains "conflict");
  - the normalization input has each raw label and the lines `D01 | <description> | <quotes>`;
  - hospital_course calls have a `Problem: <name>` line, and each section call names exactly one section_id;
  - the `problem` key is always present on `section_drafted` and on draft claims;
  - problem subheadings are headings named by the problem.
- The stub edits to `tests/section_stub.py`, `tests/test_api.py` and the 06/07/08 tests are accepted.
