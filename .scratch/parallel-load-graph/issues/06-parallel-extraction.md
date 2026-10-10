# 06: Parallel extraction + conflict check

**What to build:** Loading extracts every note in its own model call at the same time (LangGraph `Send` per note, `max_concurrency` 6), while one conflict-check call reads all passages and returns only conflicts with a verbatim quote from each conflicting passage. A merge step sorts events by note and passage order, numbers them E01… the same way every run, and validates quotes. Events gain a `problem` field. The resident sees each note marked done as it finishes. The Medication A conflict (D01) is still found. Load time is measured against the baseline (case_001: 41–55 s). Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 03a, 03b

**Status:** ready-for-agent

- [ ] One extraction call per note, run concurrently with a cap of 6
- [ ] Conflict check runs alongside extraction; conflict quotes are validated against passages
- [ ] Event numbering is identical across runs for identical model output
- [ ] Per-note "extracted" events stream and render in the UI
- [ ] `live`: case_001 still yields the Medication A conflict; load time recorded and compared with baseline

## Comments

- From 01: drop the extraction timeout (`TIMEOUT` in `core/extract.py`) from 90 s to 35 s once extraction is one call per note.
