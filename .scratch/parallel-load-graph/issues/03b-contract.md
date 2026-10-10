# 03b implementation contract

Source of truth for ticket 03b (`03b-frontend-tracer.md`). Spec: `../spec.md` ("Frontend"). Backend from 03a: `03a-contract.md`.

## Requested behavior
A React 19 + Vite + TypeScript frontend in `frontend/`, styled with flowbite-react (0.12.x) on Tailwind CSS 4, built to static files in `frontend/dist/` and served by FastAPI as a single-page app. The resident picks a case, watches every streamed load event appear live, then reads the draft by section with citation markers that open the exact source passage.

## Backend changes (api/app.py)
- `GET /api/template` → `200 {"sections": [...]}`: the `sections` list of `core/template.json` as is (`section_id`, `title`, `purpose`, `optional`), in template order.
- SPA mount at `/`, registered after all API routes: an existing file under `frontend/dist/` is served; any other non-API path returns `index.html`; any unknown path under `/api/` still returns 404 (not `index.html`). If `frontend/dist/` does not exist, no mount (API still works). Pattern: allec-rag `src/api/app.py` `SinglePageApplicationFiles`.

## Build and repo
- `frontend/package.json` scripts: `build` = `tsc --noEmit && vite build`, `test` = `vitest run`. One command builds: `npm --prefix frontend run build` (after `npm --prefix frontend install`).
- Deps: `react`, `react-dom` (19), `flowbite-react`; dev: `typescript`, `vite`, `@vitejs/plugin-react`, `tailwindcss` (4), `@tailwindcss/vite`, `vitest`, `@testing-library/react`, `@testing-library/user-event`, `jsdom`, `@types/react`, `@types/react-dom`. Nothing else without reason. flowbite-react setup per its own init/Vite plugin.
- `frontend/dist/` is committed to git (user decision). `frontend/node_modules/` is git-ignored. Any frontend change ships with a rebuilt `dist/`.

## UI behavior
- **Synthetic-data warning:** always visible at the top: "SYNTHETIC DEMONSTRATION — NOT FOR CLINICAL USE".
- **Case picker:** lists `GET /api/cases`. Load button: `POST /api/sessions {case_id}`, then `POST /api/sessions/{id}/load`, consumed with `fetch` + `ReadableStream` reader (not `EventSource`), parsing SSE blocks (`event:` / `data:` lines, blank-line delimited, possibly split across chunks). Picker and Load are disabled while a load runs. After a load ends, picking a case and pressing Load creates a new session.
- **Live progress timeline:** each SSE event is appended the moment it is parsed, before the stream ends, showing the event name, elapsed seconds since Load was pressed, and its details: `extraction_done` → event count and warnings; `draft` → claim count and warnings; `done`; `error` → detail. While running, a spinner shows the current step ("Extracting" until `extraction_done`, then "Drafting" until `draft`). Any unrecognized event name is still appended by name (forward-compatible with later tickets' events).
- **Draft:** rendered when the `draft` event arrives. The frontend then fetches `GET /api/sessions/{id}` for `passages` and `GET /api/template` (once) for section order and titles. Sections in template order; a required section with no claims shows "Not documented in the supplied notes."; an optional section with no claims is omitted. Each claim shows its text then one marker per `evidence_span_id`, labeled with `passages[id].marker` (e.g. `[N04:B07]`). `needs_review` claims render plain (badge deferred to 04).
- **Citation popover:** clicking a marker opens a flowbite `Popover` showing the passage's filename, page, marker and full text. Clicking outside or pressing Esc closes it.
- **Errors:** an `error` event (or a failed request) shows an `Alert` with the detail and a Retry button that re-runs `POST /api/sessions/{id}/load` on the same session; the timeline restarts for the retry and the Alert clears when Retry is pressed (planner default, untested).

## Seams fixed by test-architect
- `frontend/src/App.tsx` default export `App` (the only module tests import).
- `api/app.py` reads the UI directory from env var `DISCHARGE_UI_DIR` at import, default `<repo>/frontend/dist`; mounts only if it exists.

## Tests
- Frontend (vitest + Testing Library + jsdom, `fetch` stubbed): case picker lists cases and Load creates a session then starts the load; controls disabled during a load; progress events render incrementally (first event visible while the stream is still open); draft renders by section in template order with "Not documented" for empty required and omission for empty optional; marker click opens popover with filename, page, text; Esc closes it; error shows Alert and Retry reloads the same session; synthetic warning visible; SSE parser handles a block split across chunks.
- Backend (pytest, TestClient): `GET /api/template`; `/` and a client route like `/some/page` return `index.html` when dist exists; `/api/nope` returns 404; app works with no dist dir.

## Out of scope
Questions chat, corrections, approve, export, editing lock (04); conflict panel (07); needs_review badge (04); per-note/per-section events (06, 08); Streamlit retirement (05); visual polish beyond flowbite defaults; dark mode; Vite dev proxy.
