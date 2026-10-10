# 03a implementation contract

Source of truth for ticket 03a (`03a-fastapi-backend-tracer.md`). Spec: `../spec.md` ("FastAPI backend", "Load graph").

## Requested behavior
A FastAPI service in a new top-level `api/` package (beside `core/`, mirroring allec-rag's `src/api/` split: app, schemas, streaming, session store). A client lists cases, creates a session for a case, starts a load that streams progress as server-sent events, and fetches session state. The current pipeline (ingest, then `extract_events`, then `generate_draft`) runs as a two-node LangGraph graph in a new `core/load_graph.py` (nodes `extract` → `draft`, streamed with `stream_mode="updates"`, no checkpointer). Blocking graph work runs on a worker thread whose updates go onto a queue; the response drains the queue without blocking the event loop (as allec-rag `src/api/streaming.py`).

## Public interfaces
- App object: `api.app:app` (runnable with `uvicorn api.app:app`).
- `GET /api/cases` → `200 {"cases": [...]}`: the name of every directory under `fixtures/`, sorted (files such as `case_001_expected.json` and dot-directories such as `.claude` excluded; user decision after review).
- `POST /api/sessions` body `{"case_id": str}` → `201 {"session_id": str}`. Unknown case → `404`.
- `POST /api/sessions/{session_id}/load` → `200`, `text/event-stream`. Unknown session → `404`.
- `GET /api/sessions/{session_id}` → `200` session state (below). Unknown session → `404`.

## SSE events
Format: `event: <name>\ndata: <single-line JSON>\n\n`. In order on success:
1. `extraction_done` — `{"event_count": int, "warnings": [str]}`
2. `draft` — `{"draft": <Draft JSON>, "warnings": [str]}`
3. `done` — `{}`

On failure at any point: `error` — `{"detail": "<ExceptionType>: <message>"}`, and the stream ends (no `done`).

## Session state (`GET /api/sessions/{id}`)
`{"session_id", "case_id", "documents": [Document JSON], "passages": {span_id: {"text", "document_id", "filename", "page", "marker"}}, "events": [ClinicalEvent JSON], "draft": Draft JSON | null, "chat_thread_id": str, "load_running": bool}`. `marker` is `core.export.marker(span)`. Draft claims keep span IDs; the client resolves citations through `passages`.

## Invariants
- A new session has empty documents/passages/events, `draft: null`, `load_running: false`, and a chat thread ID (uuid) minted once at creation.
- During a load `load_running` is true; after it ends, success or error, it is false.
- After a successful load, state holds the case's documents, passages, events and draft.
- Retry: loading again on the same session clears events and draft first; `session_id` and `chat_thread_id` are unchanged. After an `error`, the same session can be loaded again and succeed.
- Two sessions (different cases) never see each other's documents, events or draft, including when loaded concurrently.
- Session store: in-memory, module-level, keyed by session ID, guarded by a `threading.Lock`. Nothing persisted.
- Every model call still goes through `core.llm.parse` (tests stub it there).

## Failure behavior
- Unknown case on create → 404. Unknown session on load/get → 404.
- Any exception in ingest/extract/draft → one `error` event, stream ends, `load_running` false, session reusable.
- Client disconnect mid-stream: worker runs to completion; its results still land in the session.

## Constraints
- Deps already added: `fastapi`, `uvicorn[standard]`, dev `httpx`.
- Existing modules (`core/*`, `app.py` Streamlit) keep working; fast suite and `live` suite stay green.
- Note for tests: `tests/conftest.py` has an autouse fixture that, for `live` tests, patches `core.extract.extract_events` and `core.summarize.generate_draft` with a cached case_001 run. The load graph calling them through their modules lets the live test reuse that run.

## Tests
Through FastAPI's `TestClient`, model boundary (`core.llm.parse`) stubbed. One `live` test loads case_001 end to end.

## Out of scope
- Starting a load while one is running in the same session (ticket 04 adds the lock; no 409 now).
- Ask, correction, approve, export, resolution routes; editing lock (04).
- Frontend and static file serving (03b).
- Per-note extraction, conflicts, interrupt/checkpointer (06, 07); section drafting events (08).
