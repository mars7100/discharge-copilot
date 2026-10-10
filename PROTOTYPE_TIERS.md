# Discharge Copilot — prototype status

Updated 2026-10-09 ~18:45 AST. Branch `main` @ `c08eb03` + uncommitted changes. 26 fast tests pass; 30 `live` tests pass
against the real model (`pytest -m live`, ~90 s).
Run: `.venv/bin/streamlit run app.py` → Load sample case. Every model call is live (needs `OPENAI_API_KEY`).

## Done
| Area | Status |
|---|---|
| Fixture | 6 synthetic notes, planted Medication A Day-3 conflict, hand-written `case_001_expected.json` |
| Ingest | txt + text-PDF → stable span IDs with page numbers |
| Extraction | one LLM call (~56 s), one fact per event, one flagged event per conflict, quote-gated citations, 1 retry, visible warnings |
| Draft | cited SummaryClaims, D01 flagged, "Not documented" sections |
| UI | workflow tabs: Summary (collapsible sections) · Needs review (n) · Ask about the notes (chat) · Sources · Approve & export (with export preview); citation popovers, D01 side-by-side, corrected conflict claim turns green |
| Tier B — corrections | propose → diff → accept/reject, clinician-provided label, evidence kept, approval reset |
| Tier C — questions | LangGraph classify → retrieve (all passages) → answer / read_section / clarify; validated citations; "The available notes do not establish that." (once per answer); flag attributed to the app |
| Conversation | chat UI (`st.chat_input` / `st.chat_message`); LangGraph `InMemorySaver` per `thread_id`; last 3 Q&A turns (read-section answers included) sent with each question, marked as not evidence; new thread on Load sample case |
| Approve + export | Markdown with synthetic label, status, discrepancies, clarifications, source appendix |
| Infra | live calls only (record/replay removed), Responses API (`store=False`), 120 s timeout, error handling |
| Tests | fast suite (no model) by default; `-m live` suite shares one extraction + draft per session (6 model calls) |
| Docs + checks | README; `python -m scripts.coverage` (live; last replayed run: 15/16 facts, 24/24 citations, D01 1/1) |

Spec acceptance: T01–T10, T12 automated; T11 passes by design (no speech dependency).

## Demo script (live)
1. Load sample case → **Summary** tab: open a citation popover
2. **Needs review** tab: D01 side by side
3. **Ask about the notes** (chat): "Why do the notes mention different doses?"
4. Follow-up in the same chat: "What was the reason for the Medication A dose change?"
5. **Needs review**: propose the 5 mg → 10 mg correction → Accept (C11 turns green in Summary)
6. **Ask about the notes**: "Read the condition at discharge"
7. **Approve & export**: Approve → Export

Any question works (a few seconds); failures show "Question failed".

## Next
1. Timeout: 120 s (sized for extraction, ~56 s) applies to every call; with the SDK's 2 retries, a question that hangs takes up to ~6 min to fail (only when the API stalls). Fix: short timeout for questions, long for extraction.
2. **Must be optimized:** lightweight RAG to replace "all passages" before cases get bigger (`ponytail:` in `review_graph.retrieve`); keyword retrieval was removed because it missed synonyms ("client" vs "patient").
3. OpenAI console: set `store=True` in `core/llm.py` so calls appear in Logs.
4. Accepting a correction leaves `support_status="needs_review"` (only the UI tag turns green); export still lists the claim as needs_review.
5. Coverage metric is passage-level: a fact counts as found if any claim cites its passage, so the score can be too high. Match facts in claim text if the number matters.

## Backlog — try if time allows
### Model-drafted correction from free text (spec §8.3) — ~15 min, high risk
- Add `propose_edit` intent to `core/review_graph.py`: classifier routes edit-like input ("It was 5 mg initially…") to a node that calls the LLM with the draft claims and returns `{target_claim_id, after}`.
- Validate: target claim exists; output becomes a `ProposedRevision` via `core/revise.propose` (never applied automatically).
- UI: show the proposal in the existing Clinician correction panel (Accept/Reject unchanged).
- Tests (one `live` test for the scripted correction): target resolved, draft unchanged before accept, unknown target rejected.

### Speech (spec P1, §9) — 15+ min, high risk
- `st.audio_input("Record voice")` → `OpenAI().audio.transcriptions.create(model=STT_MODEL)` (verify SDK signature first).
- Show transcript in an editable text field; submit through the same Ask / correction paths. Text input must keep working if STT fails (T11).
- Optional TTS (`ENABLE_TTS`) for short answers only, with `st.audio`.

### Smaller items
- Semantic support check for claims (spec §6.1): LLM verifier pass or keep "unverified" labels.
- Dead code: `events` no longer used in `review_graph.retrieve` (keep the `ask(..., events=())` signature for tests).
- C07 merge (Medication A order + antibiotic dose) — fixed by 2a.
