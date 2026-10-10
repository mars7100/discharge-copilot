# 05: Retire Streamlit

**What to build:** The Streamlit app is removed completely. The new FastAPI + frontend app is the only way to run Discharge Copilot, and the README describes how to set it up, run it and test it. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 04

**Status:** resolved

- [x] Streamlit app, its dependency and Streamlit-specific tests are removed
- [x] No remaining import or doc reference to Streamlit
- [x] README: setup, run (backend + frontend build), demo script, tests
- [x] Fast and `live` suites pass

## Comments

- Resolved (uncommitted). Removed `app.py`, the streamlit dependency (pyproject, uv.lock; requirements.txt re-exported, which also adds the previously missing fastapi/uvicorn), and the `AppTest` tests in `test_summarize.py` and `test_review_graph.py`. README rewritten for uvicorn + frontend build. Fast suite 88 passed; `live` 25 passed. Demo script assumes the 04 UI in the working tree.
