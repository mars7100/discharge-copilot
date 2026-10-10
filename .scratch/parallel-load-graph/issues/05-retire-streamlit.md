# 05: Retire Streamlit

**What to build:** The Streamlit app is removed completely. The new FastAPI + frontend app is the only way to run Discharge Copilot, and the README describes how to set it up, run it and test it. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Streamlit app, its dependency and Streamlit-specific tests are removed
- [ ] No remaining import or doc reference to Streamlit
- [ ] README: setup, run (backend + frontend build), demo script, tests
- [ ] Fast and `live` suites pass
