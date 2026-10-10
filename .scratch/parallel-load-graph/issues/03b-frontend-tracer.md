# 03b: Tracer: in-repo frontend shows a loaded draft

**What to build:** A React + Vite + TypeScript frontend in this repo (as in allec-rag), built to static files and served by FastAPI as a single-page app. The resident picks a case, sees streamed progress while it loads, and then sees the draft by section with citation popovers that open the exact source passage. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 03a

**Status:** resolved

- [x] One command builds the frontend; FastAPI serves it; unknown API paths still 404
- [x] Case picker starts a load; progress events render live
- [x] Draft renders by section with citation markers; a marker opens its passage (note, page, text)
- [x] Synthetic-data warning is visible
- [x] Frontend tests for case picker, progress and citation popover (vitest, as in allec-rag)

## Comments

- Resolved. Contract: `03b-contract.md`. React 19 + Vite + flowbite-react 0.12 on Tailwind 4 (user choice over hand-written CSS). `frontend/dist/` is committed (user decision), so frontend changes ship with a rebuild; `@source not "../dist"` keeps rebuilds identical. Added `GET /api/template` for section order/titles; SPA mount via `DISCHARGE_UI_DIR`. Light-only for now: `@custom-variant dark` ignores the OS setting. Review fixed Retry reloading the previous case's session, the unlabeled case picker, and dist drift. Checked in Chrome on the real model: events appear live (`extraction_done` ~32 s, `draft` ~44–65 s), popover Esc/outside-click close, phone width OK, no console errors.
