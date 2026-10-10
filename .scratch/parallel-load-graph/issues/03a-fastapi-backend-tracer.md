# 03a: Tracer: FastAPI backend with streamed load

**What to build:** A FastAPI service, laid out like allec-rag, where a client can list cases and start a load that streams progress as server-sent events. The current pipeline (extraction then draft) is wrapped as a two-node LangGraph graph; its updates stream through a worker thread and queue. Each load creates a session in an in-memory store keyed by session ID, holding documents, passages, events, draft and chat thread ID, plus whether a load is running. Session state can be fetched. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] List-cases operation returns every case under fixtures
- [ ] Start-load streams at least: extraction done, draft snapshot, done; errors stream an error event and leave the session usable for retry
- [ ] Get-session-state returns documents, draft with citations, and load-running flag
- [ ] Two sessions loading different cases do not see each other's state
- [ ] Tests through FastAPI's test client with the model boundary stubbed; one `live` test loads case_001 end to end
