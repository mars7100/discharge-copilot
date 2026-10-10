# Discharge Copilot

Hackathon prototype. It reads a hospitalization's notes, drafts a discharge summary in which every claim cites the
note passage it came from, flags conflicts between notes, answers clinician questions with citations, and lets the
clinician correct, approve and export the draft. It uses **synthetic data only** and is **not a clinical tool**.

## Setup and launch

```
uv sync                                   # or: .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # add OPENAI_API_KEY (required: every model call is live)
.venv/bin/streamlit run app.py
```

Click **Load sample case**. Extraction and the draft are live model calls (about 1 minute); questions take a few seconds.

## Demo script

1. Load sample case → **Summary** tab: open a citation popover
2. **Needs review** tab: D01 side by side
3. **Ask about the notes** (chat): "Why do the notes mention different doses?"
4. Follow-up in the same chat: "What was the reason for the Medication A dose change?"
5. **Needs review**: propose the 5 mg → 10 mg correction → Accept (C11 turns green in Summary)
6. **Ask about the notes**: "Read the condition at discharge"
7. **Approve & export**: Approve → Export

Any question works. The chat sends the last 3 question/answer turns with each new question, so follow-ups can refer
to earlier answers. Failures show "Question failed". **Load sample case** starts a new conversation.

## Architecture

1. Ingest — `core/ingest.py`: txt / text-PDF notes → passages with stable span IDs and page numbers.
2. Extract — `core/extract.py`: one LLM call → clinical events; quotes checked against the notes (`core/validate.py`).
3. Summarize — `core/summarize.py`: events → cited draft claims, discrepancies, "Not documented" sections.
4. Review graph — `core/review_graph.py`: LangGraph classify → retrieve → answer / read section / clarify. A LangGraph
   checkpointer keeps each conversation (keyed by `thread_id`); `answer` sends the last 3 turns, marked as not evidence.
5. Revise — `core/revise.py`: clinician correction proposed → diff → accept/reject.
6. Export — `core/export.py`: Markdown with status, discrepancies, clarifications and a source appendix. UI: `app.py`; all LLM calls go through `core/llm.py`.

## Tests

```
.venv/bin/python -m pytest -q -p no:cacheprovider            # fast tests, no model calls (< 1 s)
.venv/bin/python -m pytest -q -p no:cacheprovider -m live    # real model: needs the key and network (~90 s)
```

Tests marked `live` call the real model and are skipped by default. Run them after a prompt or output-schema change.
A live run extracts and drafts the sample case once (`tests/conftest.py`), shares it across tests, then asks the demo
questions: 6 model calls in total.

## Limitations

- Claims are labelled "unverified": citations are checked to exist and quotes are checked against the notes, but
  whether a passage semantically supports a claim is not checked.
- One synthetic case; model output varies between runs.
- Conversation memory is in-process: lost when the app restarts.
- No retrieval: every question sends all note passages to the model (fine for 6 short notes). **Must be optimized**
  (lightweight RAG) before larger cases.
- Discrepancy detection relies on the extraction model's `needs_review` flag (one planted conflict).
- The clinician types the corrected sentence; there is no LLM-drafted edit.
- No speech input or output.
- Not HIPAA-compliant or production-grade; human review is required.
