# Discharge Copilot — prototype status

Updated 2026-10-09 17:07 AST. Branch `main` @ `d6740c0`. 60 tests pass (`.venv/bin/python -m pytest -q -p no:cacheprovider`).
Run: `.venv/bin/streamlit run app.py` → Load sample case. App replays recorded LLM output (offline, deterministic).

## Done
| Area | Status |
|---|---|
| Fixture | 6 synthetic notes, planted Medication A Day-3 conflict, hand-written `case_001_expected.json` |
| Ingest | txt + text-PDF → stable span IDs with page numbers |
| Extraction | one LLM call, quote-gated citations, 1 retry with errors, visible warnings |
| Draft | cited SummaryClaims, D01 flagged, "Not documented" sections |
| UI | citation popovers (exact passage), D01 side-by-side |
| Tier B — corrections | propose → diff → accept/reject, clinician-provided label, evidence kept, approval reset |
| Tier C — questions | LangGraph classify → retrieve → answer / read_section / clarify; validated citations; "The available notes do not establish that."; flag attributed to the app |
| Approve + export | Markdown with synthetic label, status, discrepancies, clarifications, source appendix |
| Infra | record/replay, Responses API (`store=False`), 30 s timeout, error handling |

Spec acceptance: T01–T10, T12 automated; T11 passes by design (no speech dependency).

## Demo script (offline, deterministic)
1. Load sample case → open a citation popover
2. Show D01 side by side
3. Ask "Why do the notes mention different doses?"
4. Ask "What was the reason for the Medication A dose change?"
5. Propose the 5 mg → 10 mg correction → Accept
6. Ask "Read the condition at discharge"
7. Approve → Export

Other questions go live (network + key, a few seconds); failures show "Question failed".

## Next (prompt for another session — see chat)
1. README (launch, demo, limitations)
2. Coverage check vs expected facts (2c)
3. Extraction prompt fix (2a) + full re-record cascade

## Backlog — try if time allows
### Model-drafted correction from free text (spec §8.3) — ~15 min, high risk
- Add `propose_edit` intent to `core/review_graph.py`: classifier routes edit-like input ("It was 5 mg initially…") to a node that calls the LLM with the draft claims and returns `{target_claim_id, after}`.
- Validate: target claim exists; output becomes a `ProposedRevision` via `core/revise.propose` (never applied automatically).
- UI: show the proposal in the existing Clinician correction panel (Accept/Reject unchanged).
- Needs recordings for the scripted correction; tests: target resolved, draft unchanged before accept, unknown target rejected.

### Speech (spec P1, §9) — 15+ min, high risk
- `st.audio_input("Record voice")` → `OpenAI().audio.transcriptions.create(model=STT_MODEL)` (verify SDK signature first).
- Show transcript in an editable text field; submit through the same Ask / correction paths. Text input must keep working if STT fails (T11).
- Optional TTS (`ENABLE_TTS`) for short answers only, with `st.audio`.

### Smaller items
- Semantic support check for claims (spec §6.1): LLM verifier pass or keep "unverified" labels.
- Retrieval over event statements (spec §7.5) — removed in review because a combined event leaked the conflict into an unrelated question; needs a guard (e.g. only single-fact events).
- Discrepancy matching uses ≥1 shared word (a 2-word rule breaks "Why do the notes mention different doses?"); synonym list or classifier if stricter matching is needed.
- Dead code: `events` no longer used in `review_graph.retrieve` (keep the `ask(..., events=())` signature for tests).
- C07 merges unrelated facts (Medication A order + antibiotic dose) — fixed by 2a.
