# Discharge Copilot

Hackathon prototype. It reads a hospitalization's notes, drafts a discharge summary in which every claim cites the
note passage it came from, flags conflicts between notes, answers clinician questions with citations, and lets the
clinician correct, approve and export the draft. It uses **synthetic data only** and is **not a clinical tool**.

## Setup and launch

```
uv sync                                   # or: .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # add OPENAI_API_KEY (required: every model call is live)
.venv/bin/uvicorn api.app:app             # API + built frontend at http://127.0.0.1:8000
```

The built frontend (`frontend/dist/`) is committed. After changing `frontend/src/`, rebuild it:

```
cd frontend && npm install && npm run build
```

Pick a case and click **Load**. Extraction and the draft are live model calls (about 1 minute) and stream in as they
finish; review controls stay disabled until the load is done. Questions take a few seconds.

## Demo script

1. Load `case_001` → open a citation marker on a claim to see its source passage
2. **Discrepancies**: D01 with both source passages side by side
3. **Ask about the notes**: "Why do the notes mention different doses?"
4. Follow-up in the same chat: "What was the reason for the Medication A dose change?"
5. **Correct a claim**: pick the needs-review claim, enter the 5 mg → 10 mg correction → **Propose correction** →
   **Accept** (the claim's badge turns green)
6. **Ask about the notes**: "Read the condition at discharge"
7. **Approve and export**: **Approve** → **Export Markdown**

Any question works. The chat sends the last 3 question/answer turns with each new question, so follow-ups can refer
to earlier answers. Failures show "Question failed". Loading a case starts a new conversation.

## Architecture

1. Ingest — `core/ingest.py`: txt / text-PDF notes → passages with stable span IDs and page numbers.
2. Extract — `core/extract.py`: one LLM call → clinical events; quotes checked against the notes (`core/validate.py`).
3. Summarize — `core/summarize.py`: events → cited draft claims, discrepancies, "Not documented" sections.
4. Review graph — `core/review_graph.py`: LangGraph classify → retrieve → answer / read section / clarify. A LangGraph
   checkpointer keeps each conversation (keyed by `thread_id`); `answer` sends the last 3 turns, marked as not evidence.
5. Revise — `core/revise.py`: clinician correction proposed → diff → accept/reject.
6. Export — `core/export.py`: Markdown with status, discrepancies, clarifications and a source appendix. All LLM calls go through `core/llm.py`.
7. App — `api/` (FastAPI: sessions, streamed load, review endpoints) and `frontend/` (React + flowbite-react).

## Tests

```
.venv/bin/python -m pytest -q -p no:cacheprovider            # fast tests, no model calls (< 1 s)
.venv/bin/python -m pytest -q -p no:cacheprovider -m live    # real model: needs the key and network (~90 s)
cd frontend && npm test                                       # frontend tests (vitest, fetch stubbed)
```

Tests marked `live` call the real model and are skipped by default. Run them after a prompt or output-schema change.
A live run extracts and drafts the sample case once (`tests/conftest.py`), shares it across tests, then asks the demo
questions: 6 model calls in total.

## Limitations

- Claims are labelled "unverified": citations are checked to exist and quotes are checked against the notes, but
  whether a passage semantically supports a claim is not checked.
- One synthetic case; model output varies between runs.
- Sessions and conversation memory are in-process: lost when the server restarts.
- No retrieval: every question sends all note passages to the model (fine for 6 short notes). **Must be optimized**
  (lightweight RAG) before larger cases.
- Discrepancy detection relies on the extraction model's `needs_review` flag (one planted conflict).
- The clinician types the corrected sentence; there is no LLM-drafted edit.
- No speech input or output.
- Not HIPAA-compliant or production-grade; human review is required.
