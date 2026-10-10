# 11: Failed-note background retry

**What to build:** If a note's extraction fails after its validation retry, the load continues without it and the resident is told. The note is retried in the background; on success its events are merged, only the sections those events belong to are redrafted, and dedupe reruns. If it still fails, the resident is told the draft is missing that note. Editing stays locked until all retries settle. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 09, 10

**Status:** resolved

- [x] A failing note does not fail the load; note-failed and note-retrying events stream and render
- [x] On retry success only affected sections are redrafted; dedupe reruns; draft snapshot streams
- [x] On final failure a warning names the missing note
- [x] Done (and unlock) is sent only after retries settle

## Comments

- Resolved in 4e76a7d. Contract: `11-contract.md`. No live test (failures cannot be triggered on demand); covered by stubbed graph/API/frontend tests. Retries run after the first draft (LangGraph supersteps are lockstep). Non-hospital-course sections are all redrafted when any event is added (they receive all events); hospital course redrafts only affected problem groups. Review fixed a variable-shadowing bug in problems.normalize (regression test in tests/test_ticket11_review.py).
