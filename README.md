# Discharge Copilot

Hackathon prototype. It reads a hospitalization's notes, drafts a discharge summary in which every claim cites the
note passage it came from, flags conflicts between notes, answers clinician questions with citations, and lets the
clinician correct, approve and export the draft. It uses **synthetic data only** and is **not a clinical tool**.

## Setup and launch

```
uv sync                                   # or: .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # add OPENAI_API_KEY (only needed for unrecorded questions or re-recording)
.venv/bin/streamlit run app.py
```

Click **Load sample case**. By default it runs offline, replaying recorded LLM output (`LLM_MODE=replay`).

## Demo script

1. Load sample case → open a citation popover
2. Show D01 side by side
3. Ask "Why do the notes mention different doses?"
4. Ask "What was the reason for the Medication A dose change?"
5. Propose the 5 mg → 10 mg correction → Accept
6. Ask "Read the condition at discharge"
7. Approve → Export

Other questions call the LLM live (network + key); failures show "Question failed".

## Architecture

1. Ingest — `core/ingest.py`: txt / text-PDF notes → passages with stable span IDs and page numbers.
2. Extract — `core/extract.py`: one LLM call → clinical events; quotes checked against the notes (`core/validate.py`).
3. Summarize — `core/summarize.py`: events → cited draft claims, discrepancies, "Not documented" sections.
4. Review graph — `core/review_graph.py`: LangGraph classify → retrieve → answer / read section / clarify.
5. Revise — `core/revise.py`: clinician correction proposed → diff → accept/reject.
6. Export — `core/export.py`: Markdown with status, discrepancies, clarifications and a source appendix. UI: `app.py`; all LLM calls go through `core/llm.py`.

## Tests and re-recording

```
.venv/bin/python -m pytest -q -p no:cacheprovider
```

LLM calls are recorded in `fixtures/recorded/`, one file per request, named by a hash of the request. Changing a
prompt changes the hash, so re-record the affected calls with `LLM_MODE=record` (needs the key and network), e.g.
run the app or the pipeline with `LLM_MODE=record`, then delete recordings nothing uses any more.

## Limitations

- Claims are labelled "unverified": citations are checked to exist and quotes are checked against the notes, but
  whether a passage semantically supports a claim is not checked.
- The app replays a recorded LLM run of one synthetic case.
- Retrieval is keyword-based over passage text only (event statements were dropped, a deviation from spec §7.5).
- Discrepancy detection relies on the extraction model's `needs_review` flag (one planted conflict).
- The clinician types the corrected sentence; there is no LLM-drafted edit.
- No speech input or output.
- Not HIPAA-compliant or production-grade; human review is required.
