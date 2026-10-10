# 07: Resolve conflicts first

**What to build:** When conflicts are found, the load pauses before drafting (LangGraph `interrupt`, checkpointed by session thread) and the frontend shows each conflict with its source passages, notes and dates. The resident resolves each one by picking a documented value or typing a clarification; submitting resumes the load (`Command(resume=...)`). Each resolution becomes a clinician-provided fact that keeps both original quotes, and the draft is built only from resolved facts. A case with no conflicts drafts without pausing. Export lists resolutions. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 06

**Status:** resolved

- [x] Conflicts-found event pauses the stream; nothing is drafted before resolution
- [x] Resolution panel supports pick-a-value and free-text clarification; all conflicts must be resolved to submit
- [x] Resume continues streaming to done; resolved value appears in the draft with clinician-provided provenance and both source citations
- [x] Case without conflicts goes straight to drafting
- [x] `live`: case_001 pauses on Medication A; resolving "5 mg initially, 10 mg from Day 3" yields a draft stating it

## Comments

- Ticket 06 skipped `tests/test_summarize.py::test_case_001_draft_flags_only_the_medication_conflict` (no flagged claims until resolutions exist). Unskip it here.
- Resolved. Contract: `07-contract.md`. Deviation: "Unresolved discrepancies" in export lists discrepancies without a resolution (a ticket 04 correction sets `clarified_pending_approval` without resolving).
- Live case_001, 2026-10-10: the load pauses on D01, "Medication A dose differs on hospital day 3" ([N04:B07] "10 mg daily" vs [N05:B04] "5 mg given this shift"), after 24.2 s. Resolving with "Medication A 5 mg initially, 10 mg from Day 3" → done 17.5 s later. Claim C08 (hospital_course) states it, cites both spans, carries D01 and `needs_review`; the code fallback did not fire. Coverage 13/16 (F02, F09, F10 missing).
- `tests/test_review_graph.py::test_conflict_question_retrieves_both_conflict_spans` now asserts the discrepancy status is unchanged by `ask` instead of `== "open"` (the shared live fixture resolves D01 first). User decision.
- Deferred review findings:
  - `api/streaming.py`: `run_load` and `run_resume` repeat the same try/except; it can live once in the thread target (−4 lines).
  - `InMemorySaver` keeps every load thread's checkpoints, including abandoned pauses; memory grows for the life of the process.
  - A new load started while a resume is drafting lets both workers write to the session (the same race existed between two concurrent loads).
  - Accessibility: each conflict's radios have no `fieldset`/`legend`, so a screen reader announces "Use this value" without the conflict.
  - A document without date or hospital day shows "(Hospital Day )" in the panel.
  - The panel is not restored after a page refresh; Load stays enabled while paused (a new load discards the pause).
