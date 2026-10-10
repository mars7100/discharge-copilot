# 01: Prefactor: per-call timeouts and one retry layer

**What to build:** Each kind of model call (extraction, conflict check, section draft, dedupe, question) gets its own timeout instead of the shared 120 s, and the OpenAI client's built-in retries are off, so retries happen in one place only. A stalled question fails within its own timeout instead of after up to ~6 minutes. Behavior is otherwise unchanged. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] Every model call still goes through the single model-call boundary
- [x] Timeout is set per call kind; questions use a short timeout, extraction a long one
- [x] OpenAI client retries are disabled; any retry is done by the caller (existing validation retry or graph retry policy)
- [x] Fast test suite passes; `live` suite passes

## Comments

- Resolved in `5de2384`. Timeouts: extraction 90 s (one call over all notes measured 42.4 s on case_001), draft 35 s, question 35 s. OpenAI `max_retries=0`. The question node gets a LangGraph `RetryPolicy(max_attempts=2)` limited to transient errors (`llm.TRANSIENT`: connection/timeout, rate limit, 5xx), since it has no caller retry loop. Conflict-check and dedupe timeouts are added with their calls in 07 and 10. Extraction drops to 35 s in 06.
