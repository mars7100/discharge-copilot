# Discharge Copilot — prototype status

Updated 2026-10-09 ~17:45 AST. Branch `main` @ `af89027`. 59 tests pass (`.venv/bin/python -m pytest -q -p no:cacheprovider`).
Run: `.venv/bin/streamlit run app.py` → Load sample case. App replays recorded LLM output (offline, deterministic).

## Done
| Area | Status |
|---|---|
| Fixture | 6 synthetic notes, planted Medication A Day-3 conflict, hand-written `case_001_expected.json` |
| Ingest | txt + text-PDF → stable span IDs with page numbers |
| Extraction | one LLM call (~56 s), one fact per event, one flagged event per conflict, quote-gated citations, 1 retry, visible warnings |
| Draft | cited SummaryClaims, D01 flagged, "Not documented" sections |
| UI | citation popovers (exact passage), D01 side-by-side, corrected conflict claim turns green |
| Tier B — corrections | propose → diff → accept/reject, clinician-provided label, evidence kept, approval reset |
| Tier C — questions | LangGraph classify → retrieve (all passages) → answer / read_section / clarify; validated citations; "The available notes do not establish that."; flag attributed to the app |
| Approve + export | Markdown with synthetic label, status, discrepancies, clarifications, source appendix |
| Infra | record/replay, Responses API (`store=False`), 120 s timeout, error handling |
| Docs + checks | README; `python -m scripts.coverage` (15/16 facts, 24/24 citations, D01 1/1) |

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

Also recorded: "what was the clients condition?".

## Next
1. Follow-up questions: send the session's previous Q&A with each new question (chat history in the `answer` prompt); re-record scripted questions.
2. "Not established" wording: the model tacks the exact sentence onto answers that already say it ("…do not establish why the doses differ. The available notes do not establish that."; "…documentation; The available notes do not establish that."). Fix in the `review_graph.SYSTEM` prompt (e.g. use it only when nothing relevant is documented) + re-record.
3. Timeout: 120 s applies to every call, so a hanging live question takes up to ~6 min (SDK retries ×2) to fail. Option: default 30 s, `LLM_TIMEOUT` env override for recording; restore the 30 s test.
4. Lightweight RAG to replace "all passages" when cases get bigger (`ponytail:` in `review_graph.retrieve`); keyword retrieval was removed because it missed synonyms ("client" vs "patient").
5. OpenAI console: calls don't appear in Logs because of `store=False` (`core/llm.py`); changing it changes every request hash → full re-record.
6. Accepting a correction leaves `support_status="needs_review"` (only the UI tag turns green); export still lists the claim as needs_review.
7. Coverage metric is passage-level, so it can't show per-fact extraction gains; sentence-level matching if needed.

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
- Dead code: `events` no longer used in `review_graph.retrieve` (keep the `ask(..., events=())` signature for tests).
- C07 merge (Medication A order + antibiotic dose) — fixed by 2a.
