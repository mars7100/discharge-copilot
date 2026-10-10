# 07: Resolve conflicts first

**What to build:** When conflicts are found, the load pauses before drafting (LangGraph `interrupt`, checkpointed by session thread) and the frontend shows each conflict with its source passages, notes and dates. The resident resolves each one by picking a documented value or typing a clarification; submitting resumes the load (`Command(resume=...)`). Each resolution becomes a clinician-provided fact that keeps both original quotes, and the draft is built only from resolved facts. A case with no conflicts drafts without pausing. Export lists resolutions. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Conflicts-found event pauses the stream; nothing is drafted before resolution
- [ ] Resolution panel supports pick-a-value and free-text clarification; all conflicts must be resolved to submit
- [ ] Resume continues streaming to done; resolved value appears in the draft with clinician-provided provenance and both source citations
- [ ] Case without conflicts goes straight to drafting
- [ ] `live`: case_001 pauses on Medication A; resolving "5 mg initially, 10 mg from Day 3" yields a draft stating it

## Comments

- Ticket 06 skipped `tests/test_summarize.py::test_case_001_draft_flags_only_the_medication_conflict` (no flagged claims until resolutions exist). Unskip it here.
