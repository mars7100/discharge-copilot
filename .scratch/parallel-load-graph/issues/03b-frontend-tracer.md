# 03b: Tracer: in-repo frontend shows a loaded draft

**What to build:** A React + Vite + TypeScript frontend in this repo (as in allec-rag), built to static files and served by FastAPI as a single-page app. The resident picks a case, sees streamed progress while it loads, and then sees the draft by section with citation popovers that open the exact source passage. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 03a

**Status:** ready-for-agent

- [ ] One command builds the frontend; FastAPI serves it; unknown API paths still 404
- [ ] Case picker starts a load; progress events render live
- [ ] Draft renders by section with citation markers; a marker opens its passage (note, page, text)
- [ ] Synthetic-data warning is visible
- [ ] Frontend tests for case picker, progress and citation popover (vitest, as in allec-rag)
