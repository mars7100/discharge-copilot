# 01: Prefactor: per-call timeouts and one retry layer

**What to build:** Each kind of model call (extraction, conflict check, section draft, dedupe, question) gets its own timeout instead of the shared 120 s, and the OpenAI client's built-in retries are off, so retries happen in one place only. A stalled question fails within its own timeout instead of after up to ~6 minutes. Behavior is otherwise unchanged. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Every model call still goes through the single model-call boundary
- [ ] Timeout is set per call kind; questions use a short timeout, extraction a long one
- [ ] OpenAI client retries are disabled; any retry is done by the caller (existing validation retry or graph retry policy)
- [ ] Fast test suite passes; `live` suite passes
