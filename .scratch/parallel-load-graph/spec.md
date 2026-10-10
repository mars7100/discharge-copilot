# Spec: Parallel load graph, resolve-first conflicts, FastAPI + in-repo frontend

Status: ready-for-agent
Created: 2026-10-09

## Problem Statement

A resident loading a case waits about 40–55 seconds before seeing anything. Loading makes two model calls in sequence: one extraction call that writes every event for every note (4.9k–7.6k output tokens, 23–35 s), then one draft call (2.6k–2.8k output tokens, ~18 s). Time to first token is only 5–7 s per call; the rest is the model writing output, so the wait grows with the length of the notes. case_003 has 15 notes and about 2.4× the text of case_001.

The draft is also written before conflicts between notes are resolved. A conflict such as the Medication A dose (5 mg in the nursing note, 10 mg in the progress note, both Hospital Day 3) goes into the draft as an unresolved claim, and the resident has to correct it afterwards. Medication-list discrepancies are the most documented source of discharge summary errors, and lists filled in automatically go stale when they are filled before reconciliation.

The summary's sections also leave out elements the Joint Commission expects: procedures, discharge diagnoses, discharge medications and information given to the patient. The hospital course is not organized by problem, the way clinicians usually write it.

The app is a Streamlit prototype. The intended product is a FastAPI backend plus a frontend in the same repo.

## Solution

Loading a case runs as a LangGraph graph in two phases, served over FastAPI with live progress streamed to an in-repo frontend.

**Phase 1, analyze.**
- Every note is extracted in its own model call, all at the same time with a concurrency cap.
- Alongside those calls, one conflict-check call reads all the notes and returns only the facts that disagree.
- The events are merged, their quotes are checked against the notes, and problem names are made consistent across notes.
- If there are conflicts, the graph pauses and the frontend shows each conflict with its source passages.
- The resident resolves each conflict, either by picking one of the documented values or by typing a clarification.

**Phase 2, draft.** It runs only on resolved facts.
- Each section is drafted in its own model call, at the same time; the hospital course gets one call per problem.
- For optional sections, each section call decides through structured output whether the notes document anything for it.
- One dedupe call returns the IDs of duplicate claims, and code removes those claims.

The draft streams to the frontend as it is built, so the resident sees progress, but all editing is locked until the load reports done. If a note's extraction fails, the load carries on without that note. The note is retried in the background, and when the retry succeeds, only the sections its events belong to are redrafted.

## User Stories

1. As a resident, I want to pick a case from the list of available cases, so that I can load the hospitalization I'm documenting.
2. As a resident, I want loading to start as soon as I select a case, so that I don't have to take an extra step.
3. As a resident, I want to see live progress while the case loads, so that I know the app is working and what it's doing.
4. As a resident, I want to see each note marked done as its extraction finishes, so that I can tell how far along the analysis is.
5. As a resident, I want the analysis phase to take roughly as long as the slowest single note rather than the sum of all notes, so that larger cases don't make me wait proportionally longer.
6. As a resident, I want to be told when a note's extraction failed and is being retried, so that I understand why that note isn't reflected yet.
7. As a resident, I want a failed note not to block the whole load, so that one flaky model call doesn't stop my work.
8. As a resident, I want a failed note's facts to appear in the draft once its retry succeeds, so that the summary isn't silently missing a note.
9. As a resident, I want only the sections affected by a retried note to be redrafted, so that the rest of the draft stays stable.
10. As a resident, I want to be told if a note still fails after its retries, so that I know the draft is missing that note.
11. As a resident, I want conflicts between notes to be found before any draft is written, so that the draft is built from reconciled facts.
12. As a resident, I want conflicts to be found even when they span notes extracted separately, so that splitting the work doesn't hide disagreements.
13. As a resident, I want each conflict shown with the exact passages, notes and dates it comes from, so that I can judge it from the source.
14. As a resident, I want to resolve a conflict by choosing one of the documented values, so that a simple case takes one click.
15. As a resident, I want to resolve a conflict by typing a clarification (for example "5 mg initially, changed to 10 mg on Day 3"), so that I can record what actually happened when neither value is complete.
16. As a resident, I want my resolution labelled as clinician-provided and kept with both original source quotes, so that the provenance of the final wording is auditable.
17. As a resident, I want the app never to resolve a conflict on its own, so that clinical judgment stays with me.
18. As a resident, I want drafting to start only after every conflict is resolved, so that the draft is written once, from facts I've reconciled.
19. As a resident, I want a case with no conflicts to go straight to drafting, so that I'm not stopped for nothing.
20. As a resident, I want the draft to appear section by section as it is generated, so that I can start reading early.
21. As a resident, I want editing, questions, approval and export disabled until the load is done, so that I never act on a draft that's about to change.
22. As a resident, I want a clear "done" signal that unlocks the draft, so that I know it's final.
23. As a resident, I want the hospital course organized by problem (for example pneumonia, hypertension), so that it reads the way discharge summaries are normally written.
24. As a resident, I want the same problem recognized under different names across notes (for example "CAP" and "community-acquired pneumonia"), so that one problem isn't split into two.
25. As a resident, I want each problem's hospital course condensed to the events that changed the stay, so that the summary is short enough to be useful.
26. As a resident, I want a key tests and interventions section, so that important workup and treatment are easy to find.
27. As a resident, I want discharge diagnoses included when the notes document them, so that the summary covers that required element.
28. As a resident, I want discharge medications included when the notes document them, built from resolved medication facts, so that the list reflects reconciliation.
29. As a resident, I want procedures included when the notes document them, so that the summary covers that required element.
30. As a resident, I want patient instructions and information given to the patient included when the notes document them, so that the summary covers that required element.
31. As a resident, I want pending items included when the notes document them, so that the follow-up clinician knows what's outstanding.
32. As a resident, I want optional sections the notes say nothing about to be left out, so that the summary isn't padded with empty headings.
33. As a resident, I want every claim to cite the note passages it rests on, so that I can verify it.
34. As a resident, I want citations to open the exact source passage, so that checking a claim is fast.
35. As a resident, I want the same fact not to appear twice across sections, so that the summary isn't repetitive.
36. As a resident, I want duplicate removal never to delete the claim that carries my conflict resolution, so that my reconciliation can't be lost.
37. As a resident, I want claim numbering to be stable and in section order, so that I can refer to claims consistently.
38. As a resident, I want to ask questions about the notes after the load is done and get cited answers, so that I can check details without reading every note.
39. As a resident, I want follow-up questions to understand the earlier conversation, so that I can ask naturally.
40. As a resident, I want to propose a correction to a claim and accept or reject it, so that I can fix wording that isn't covered by conflict resolution.
41. As a resident, I want to approve the draft explicitly, so that nothing is final without my sign-off.
42. As a resident, I want to export the approved draft as Markdown with citations, the synthetic-data label, my resolutions and a source appendix, so that I have a document to hand off.
43. As a resident, I want loading a new case to start a fresh session, so that one case's conversation and resolutions don't leak into another.
44. As a resident, I want a clear error if the load fails outright, so that I can retry instead of waiting indefinitely.
45. As a resident, I want a stalled model call to fail within a bounded time, so that a hung request doesn't freeze the app for minutes.
46. As a developer, I want every model call to go through the single model-call boundary, so that tests can stub all model behavior in one place.
47. As a developer, I want the load graph runnable and testable on its own before the API exists, so that the speed work can be measured independently of the migration.
48. As a developer, I want the drop-list returned by the dedupe call to be restricted by the output schema to claim IDs that exist, so that the model cannot invent IDs.
49. As a developer, I want the API to refuse editing operations while a load is running, so that the lock holds even if the frontend misbehaves.
50. As a developer, I want each session's state kept on the server and keyed by session, so that concurrent browser tabs don't interfere.
51. As a developer, I want the frontend built and served by FastAPI from this repo, matching the allec-rag layout, so that there's one service to run.
52. As a developer, I want load time measured against the current baseline (about 41–55 s for case_001), so that the optimization is verified rather than assumed.

## Implementation Decisions

**Load graph (new module).** A LangGraph graph owns the whole load. The app or API only starts it, streams its updates and resumes it.

- **Phase 1 nodes.**
  - **Per-note extraction** is fanned out with one `Send` per note. Each branch runs the existing extraction prompt on one note's passages, with the conflict rules removed, and with a new `problem` field on each event.
  - **The conflict-check node** runs in parallel with the per-note branches. It reads all passages and returns conflict items only, each with a verbatim quote from every conflicting passage.
  - **The merge node** sorts events by note and passage order, numbers them (E01…) so numbering doesn't change between runs, and runs the existing quote validation.
  - **The problem-normalization node** is one small model call that maps per-note problem labels onto one canonical list.
- **Concurrency.** Branches run with `max_concurrency` = 6 in the run config.
- **Pause and resume.**
  - **Pause.** If conflicts exist, a node calls LangGraph `interrupt(...)` with the conflicts. The graph's state is checkpointed, keyed by the session's thread ID.
  - **Resume.** The graph resumes with `Command(resume=resolutions)`. Each resolution is either one of the documented values or free-text clarification.
  - **What a resolution becomes.** Each one turns into a clinician-provided resolved fact that keeps both original quotes. Drafting sees resolved facts, never raw conflicting events.
- **Phase 2 nodes.**
  - **Section drafting** is fanned out with one call per section, and the hospital course is fanned out further with one call per canonical problem.
  - **Section output.** Each section call returns structured output: a `documented` decision and its claims. Code drops a section when `documented` is false. It treats `documented: true` with no claims as a warning.
  - **Problem grouping.** The hospital-course prompt groups by problem and condenses to events that changed the stay.
- **Dedupe.**
  - **The call.** One call over all joined claims returns only the claim IDs to drop. The drop list's item type is built at runtime as an enum of the existing claim IDs, so strict structured outputs cannot return an unknown ID. A locally generated schema produced `"items": {"type": "string", "enum": [...]}`; a live call with it has not been run yet.
  - **The guard.** Code applies the drops, but refuses any drop that would remove the last claim carrying a clinician resolution.
- **Claims and IDs.** Claims are numbered (C01…) after the join, in section order. Citation validation of claims is unchanged (cited span IDs must exist).
- **Failed note.**
  - **Load continues.** A per-note failure, after the node's internal validation retry, does not fail the load. The draft proceeds without that note.
  - **Background retry.** The note is retried in the background.
  - **On success.** Its events are merged, the sections those events map to are redrafted, and dedupe reruns.
  - **No new conflicts.** A retried note cannot introduce an unseen conflict, because the conflict check reads raw passages, not extracted events.
- **Retries and timeouts.**
  - **One retry layer.** API exceptions are retried by LangGraph `RetryPolicy` on the node, and the OpenAI client's own `max_retries` is set to 0 so the two retry layers don't multiply.
  - **Timeouts.** Each call type gets its own timeout instead of the global 120 s.
- **Section template.**
  - **Shape.** Sections are declared as data, following the municipal-document-ai template pattern: each has an ID, a title, a purpose for the prompt, and an `optional` flag.
  - **Required sections:** reason for admission, hospital course, condition at discharge, follow-up.
  - **Optional sections:** key tests and interventions, discharge diagnoses, discharge medications, procedures, patient instructions, pending items.
  - **Who decides optional sections.** The AI, through each section call's structured output, not the user and not a fixed flag.
- **Schema changes.**
  - **Events.** Events gain `problem`. The per-note extraction no longer sets `needs_review`.
  - **New types.** A conflict item (conflicting quotes with span IDs) and a resolution (conflict ID, chosen value or clarification text, clinician-provided provenance).
  - **Claims.** Claims gain the new optional section IDs.
- **Existing modules kept.**
  - **Ingest.** Unchanged.
  - **Validation.** The quote and citation checks are reused.
  - **Review graph.** The questions chat is kept and runs only after the load is done.
  - **Revise.** The correction flow is kept for edits after drafting; conflicts no longer go through it.
  - **Export.** Gains the new sections and lists resolutions.

**FastAPI backend (new).** It mirrors the allec-rag layout.
- **Streaming.** Blocking graph work runs on a worker thread whose updates go onto a queue, and the response streams them as server-sent events.
- **Operations:**
  - list cases;
  - start a load (streams events);
  - submit resolutions (resumes the graph, keeps streaming);
  - get session state;
  - ask a question;
  - propose a correction;
  - accept or reject a correction;
  - approve;
  - export.
- **Streamed event kinds:**
  - note extracted;
  - note failed;
  - note retrying;
  - conflicts found (the pause);
  - section drafted;
  - section omitted;
  - dedupe applied;
  - draft snapshot;
  - done;
  - error.
- **Session store.** An in-memory store keyed by session ID holds:
  - documents and passages;
  - events and conflicts;
  - resolutions;
  - the draft and revisions;
  - the chat thread ID;
  - whether a load is running.
- **Editing lock.** While a load is running, the ask, correction, approve and export operations return HTTP 409.

**Frontend (new).** React + Vite + TypeScript in the same repo, built to static files and served by FastAPI as a single-page app (as in allec-rag). Views:
- case picker;
- live progress;
- conflict resolution panel;
- streaming draft with citation popovers;
- questions chat;
- correction panel;
- approve and export.

Controls are disabled until done. The Streamlit app is retired once the frontend reaches parity.

**Build order.** Each step is tested before the next:
1. The load graph on its own, timed against the baseline.
2. The FastAPI backend.
3. The frontend.

## Testing Decisions

- **What a good test is.** Good tests check external behavior through a public interface: inputs in, events and draft out. They don't check node internals or prompt wording. Detailed test design comes from the implementation workflow's test architect; this section fixes the seams and the boundaries.
- **Seam 1, the load graph's public interface.** Start a load for a case, receive a stream of updates, the graph pauses with conflicts, resume with resolutions, receive the final draft.
  - **Fast tests** cover:
    - per-note fan-out;
    - quote validation;
    - pause and resume;
    - resolutions reaching the draft with provenance;
    - section omission on `documented: false`;
    - dedupe dropping only existing IDs and never the last resolution-carrying claim;
    - numbering that doesn't change between runs;
    - failed-note retry with redraft of only the affected sections.
  - **Live tests** on case_001 check:
    - the Medication A conflict is found and pauses the graph;
    - the resolved value appears in the draft;
    - load time is recorded against the baseline.
- **Seam 2, the HTTP API** through FastAPI's test client (once the backend exists):
  - the load streams events;
  - conflicts are delivered and resolutions accepted;
  - editing operations return 409 during a load;
  - sessions are isolated from each other.
- **Model boundary.** Every model call goes through the existing single model-call module. Fast tests stub that one function; tests marked `live` call the real model and are skipped by default.
- **Prior art.**
  - The extraction tests stub the model with canned responses and check retry and validation behavior.
  - The review-graph tests stub the model and check routing and citation dropping.
  - The shared live fixture runs case_001 once per session.
  - The coverage script compares output against `case_001_expected.json`.

## Out of Scope

- Speech input and output.
- Terminology standards (SNOMED CT, RxNorm, UMLS) for matching names; fine-tuning.
- Evals for section decisions and omissions.
- A code-based medication conflict check on structured drug, dose and frequency fields; the conflict check is AI only.
- A complete, template-built key tests and interventions list; the section is AI-written for now.
- Filling sections from templates in code.
- Retrieval (RAG) for questions; questions still send all passages.
- Persistent storage, authentication, multi-user support, deployment.
- PDF/DOCX export.
- Real patient data.

## Further Notes

- **Baseline (case_001, measured 2026-10-09).** Two runs:

  | Run | Extraction | Draft |
  |---|---|---|
  | 1 | 35.5 s, 7,596 output tokens | 19.1 s |
  | 2 (streamed) | 23.1 s (first token at 4.8 s) | 17.9 s (first token at 6.9 s) |

  Output speed is about 200–240 tokens/s. Estimates, not measured: per-note extraction about 9 s; the draft phase about the same as today's single call.
- **Research behind the design.**
  - **Where model errors fall.** Published model-generated discharge summary studies find omissions and hallucinations mostly in generated text. That's why drafting sees only checked, resolved facts.
  - **Medication lists.** Medication reconciliation errors are the most documented discharge summary failure.
  - **Hospital course structure.** Clinicians usually write it by problem, condensed.
  - **Joint Commission elements.** Reason for hospitalization, procedures, care provided, condition and disposition, information given to the patient and family, follow-up.
- **Assumptions to confirm during implementation.**
  - **Required sections with no content** still show "Not documented in the supplied notes."
  - **A conflict-check call that fails after retries** fails the load, because conflicts gate drafting.
  - **The section a resolved conflict claim belongs to** is decided by the section calls like any other fact.
- **Domain docs.** The repo has no `CONTEXT.md` yet. Terms used here: passage (a span of a note), event (an extracted fact with a verbatim quote), conflict, resolution, claim, section, problem.
