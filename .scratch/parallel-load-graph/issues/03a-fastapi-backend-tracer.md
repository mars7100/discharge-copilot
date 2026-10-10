# 03a: Tracer: FastAPI backend with streamed load

**What to build:** A FastAPI service, laid out like allec-rag, where a client can list cases and start a load that streams progress as server-sent events. The current pipeline (extraction then draft) is wrapped as a two-node LangGraph graph; its updates stream through a worker thread and queue. Each load creates a session in an in-memory store keyed by session ID, holding documents, passages, events, draft and chat thread ID, plus whether a load is running. Session state can be fetched. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 01

**Status:** resolved

- [x] List-cases operation returns every case under fixtures
- [x] Start-load streams at least: extraction done, draft snapshot, done; errors stream an error event and leave the session usable for retry
- [x] Get-session-state returns documents, draft with citations, and load-running flag
- [x] Two sessions loading different cases do not see each other's state
- [x] Tests through FastAPI's test client with the model boundary stubbed; one `live` test loads case_001 end to end

## Comments

- Resolved in `5de2384`. Contract: `03a-contract.md`. Routes: `GET /api/cases`, `POST /api/sessions`, `POST /api/sessions/{id}/load` (SSE), `GET /api/sessions/{id}`. Retry reuses the session. A second load in a running session is unguarded until 04. No checkpointer until 07. Review fixed path traversal on create and two `load_running` timing gaps. Dot-directories are excluded from the case list (user decision). Checked on a real uvicorn server: `extraction_done` at 26 s, `draft` at 41 s on case_001; a client disconnect does not stop the load.
