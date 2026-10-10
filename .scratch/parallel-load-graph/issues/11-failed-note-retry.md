# 11: Failed-note background retry

**What to build:** If a note's extraction fails after its validation retry, the load continues without it and the resident is told. The note is retried in the background; on success its events are merged, only the sections those events belong to are redrafted, and dedupe reruns. If it still fails, the resident is told the draft is missing that note. Editing stays locked until all retries settle. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 09, 10

**Status:** ready-for-agent

- [ ] A failing note does not fail the load; note-failed and note-retrying events stream and render
- [ ] On retry success only affected sections are redrafted; dedupe reruns; draft snapshot streams
- [ ] On final failure a warning names the missing note
- [ ] Done (and unlock) is sent only after retries settle
