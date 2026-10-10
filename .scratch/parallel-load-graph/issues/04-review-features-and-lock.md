# 04: Review features on FastAPI + editing lock

**What to build:** Everything the Streamlit app does after loading works in the new app: the questions chat (with conversation memory per session), proposing a correction and accepting or rejecting it, approving the draft, and exporting Markdown. While a load is running, these operations return HTTP 409 and the frontend disables their controls until the done event. Spec: `.scratch/parallel-load-graph/spec.md`.

**Blocked by:** 03a, 03b

**Status:** ready-for-agent

- [ ] Ask: cited answers, follow-ups use last turns, failures show "Question failed"
- [ ] Corrections: propose shows a diff, accept updates the draft with clinician-provided label and resets approval, reject leaves it unchanged
- [ ] Approve and export: Markdown with synthetic label, status, discrepancies/resolutions, clarifications and source appendix
- [ ] Ask, correction, approve and export return 409 while load is running; UI controls disabled until done
- [ ] Demo script from the README runs end to end in the new app
