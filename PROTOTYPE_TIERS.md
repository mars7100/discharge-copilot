# Prototype tiers — presentation 2026-10-09 18:00 AST

Planned at 16:38. Built directly (no test-architect/implementer/reviewer cycle); each piece tested as built.
App runs in replay mode (recorded LLM output): instant, offline, same result every run.

## Done (steps 1–4)
- Scaffold, 6 synthetic notes + hand-written expected facts
- Models, ingestion (stable span IDs)
- Extraction with quote-gated citations, retry, record/replay; 29 tests pass

## Tier A (~45 min, target ~17:25)
- Summary generation: one LLM call → SummaryClaims citing span IDs; IDs/quotes validated
- Streamlit app:
  - Load sample case
  - Draft grouped by section
  - Click a citation → exact source passage
  - Discrepancy (Medication A, Day 3) with both passages side by side
  - Approve → Markdown export (synthetic label, source appendix)

## Tier B (~20 min, target ~17:45)
- Typed clinician correction → proposed before/after diff
- Accept / Reject; nothing changes before Accept
- Accepted text labeled clinician-provided; approval resets after any edit

## Tier C (~25 min) — does not fit before 18:00
- Typed questions answered with citations (LangGraph review loop, spec §8)

## Postponed until after the presentation
- Test architect → implementer → reviewer cycle for steps 5–8
- Extraction prompt fix (2a) + re-record (3 expected facts currently missing)
- Step 4 reviewer re-run
- Completeness check vs expected facts (2c, step 5)
- Speech (P1)

## Running it
`.venv/bin/streamlit run app.py` (run by the user; sandbox may block the local port)
