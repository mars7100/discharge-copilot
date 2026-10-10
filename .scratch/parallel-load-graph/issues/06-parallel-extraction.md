# 06: Parallel extraction + conflict check

**What to build:** Loading extracts every note in its own model call at the same time (LangGraph `Send` per note, `max_concurrency` 6), while one conflict-check call reads all passages and returns only conflicts with a verbatim quote from each conflicting passage. A merge step sorts events by note and passage order, numbers them E01… the same way every run, and validates quotes. Events gain a `problem` field. The resident sees each note marked done as it finishes. The Medication A conflict (D01) is still found. Load time is measured against the baseline (case_001: 41–55 s). Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 03a, 03b

**Status:** resolved

- [x] One extraction call per note, run concurrently with a cap of 6
- [x] Conflict check runs alongside extraction; conflict quotes are validated against passages
- [x] Event numbering is identical across runs for identical model output
- [x] Per-note "extracted" events stream and render in the UI
- [x] `live`: case_001 still yields the Medication A conflict; load time recorded and compared with baseline

## Comments

- From 01: drop the extraction timeout (`TIMEOUT` in `core/extract.py`) from 90 s to 35 s once extraction is one call per note.
- Resolved. Contract: `06-contract.md`. Extraction `TIMEOUT` is 35 s. The conflict check (`core/conflicts.py`) also has a 35 s timeout and keeps its first attempt's valid conflicts if the retry call raises (same as `extract_events`).
- Live load times, case_001, 2026-10-10 (baseline 41–55 s):

  | Run | Total | Last note done | Draft step |
  |---|---|---|---|
  | 1 | 39.6 s | 21.5 s | 18.1 s |
  | 2 | 65.1 s | 36.1 s (note_01) | 29.0 s |
  | 3 (live pytest) | 60.3 s | – | – |
  | 4 | 61.6 s | 34.4 s (note_01) | 27.2 s |

  Not reliably faster than the baseline. The single draft call (18–29 s) is now the larger cost; ticket 08 addresses it. The other 5 notes finish in 7–22 s.
- note_01 (23–28 events, the largest note) took 34–36 s in 3 of 4 runs, with no warnings. Run 2 (36.1 s) cannot be a 35 s timeout plus retry, so it was most likely a validation retry: two calls. `extract_events` reports nothing when a retry succeeds, so a retry cannot be seen. Before changing the timeout, make retries visible.
- D01 (Medication A) found in every run (note_04_p01_b07, note_05_p01_b04). Known-fact coverage varies: 15/16 (F02 missing) and 14/16 (F09 and F10 missing); no test checks it.
- `max_concurrency` 6 also counts the conflict check, so with 6 notes one extraction waits for a free slot.
- Live calls fail inside the Claude Code sandbox (OpenAI SSL, `OSStatus -26276`); run live tests outside it.
