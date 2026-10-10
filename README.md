# Discharge Copilot

Hackathon demonstration using synthetic hospitalization notes. The app extracts cited clinical
events, resolves conflicting notes with clinician input, drafts a discharge summary, and supports
review, case questions, model-proposed corrections, approval, and Word export. It is not a clinical tool.

## Set up and run

Run these commands from the repository root. Python 3.12 or later and Node.js 20.19 or later
are required. Node.js 22.12 or later also works with Vite 7.

```sh
uv sync
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Set `LLM_MODEL` to a model available to your account that supports
structured outputs. Every load, correction proposal, and model-backed question uses the live API.
The backend loads `.env` without overriding existing environment variables. Speech settings in
the example file are unused by the current UI.

The committed `frontend/dist/` lets the backend serve the app without a separate frontend server:

```sh
.venv/bin/uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. The default UI is the blue CanvasApp workspace.

For frontend development, run these commands in `frontend/` while the backend runs on port 8000:

```sh
npm ci
npm run dev
```

Open <http://127.0.0.1:5173/>. Vite proxies `/api` requests to the backend.
After changing frontend source, rebuild the committed assets from `frontend/`:

```sh
npm run build
```

## Review a case

1. Choose `case_001`, `case_002`, or `case_003`, then click **Load case**.
2. Open the **Source notes** folder. Each card represents a supplied document and shows its
   actual extraction outcome. Select a card to inspect source passages and extracted events.
   Extraction runs in parallel. The UI does not invent individual task start times.
3. If the load pauses at **Resolve conflicts**, choose a documented value or type a clinician
   clarification for each conflict. Click **Review resolutions** to inspect the exact text to store.
   Click **Edit** to change choices or **Start drafting** to submit them and resume.
4. Select **Compose the draft** to inspect sections as they arrive. When the load and final
   snapshot finish, open **Results review**. Citation buttons open the contextual source inspector.
5. Select a claim and enter a **Clinician statement**, then click **Propose correction**.
   The model proposes the revised wording. Review **Before** and **After**, then **Accept** or **Reject**.
   Accepted corrections retain clinician provenance and require approval again.
6. Open **Ask about this case** after the draft is ready. Answers stream incrementally and
   include source citations. Minimize preserves the chat. **Stop answer** retains partial output.
7. Enter a **Reviewer**, click **Approve draft**, then **Download Word document** to export DOCX.
   A pending correction blocks approval and export.

Loading or switching cases clears the current workspace and chat. **Stop watching load** stops
the browser stream, while server work continues. Reload the case to begin a fresh session.

## Run checks

From the repository root:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider
git diff --check
```

From `frontend/`:

```sh
npm test
npm run build
```

The default backend test run excludes tests marked `live`. Frontend tests stub API responses and
exercise CanvasApp. To run the live backend tests with your configured key and network access:

```sh
.venv/bin/python -m pytest -q -p no:cacheprovider -m live
```

Live tests share a real `case_001` load through the parallel load graph. Model-call counts and
timing vary with conflicts, retries, problem groups, and the questions under test.

## Code layout

- `core/ingest.py` parses text and PDF notes into source passages.
- `core/load_graph.py` orchestrates parallel extraction, conflict resolution, section drafting,
  problem grouping, deduplication, and failed-note retries.
- `core/extract.py`, `core/summarize.py`, and `core/validate.py` produce and validate cited output.
- `core/review_graph.py` classifies questions, selects evidence, answers, or reads a draft section.
  Session-specific conversation memory supplies the last three turns as context, not evidence.
- `core/revise.py` proposes corrections and records accept or reject decisions.
- `core/export.py` generates DOCX and Markdown with provenance and a source appendix.
- `api/` contains FastAPI session, load-stream, question-stream, review, and export endpoints.
  The Markdown export endpoint remains supported for existing clients.
- `frontend/src/CanvasApp.tsx` is the production frontend entry. `CanvasBase.css` contains shared
  canvas styles and `CanvasApp.css` contains connected-app styles. Attribution is in
  `CanvasBase.LICENSE.md`.
- `fixtures/` contains the three synthetic cases. `.scratch/` contains project issues and specs.

## Limitations

- Citations and quoted source text are validated, but semantic support for every claim is not.
  Claims can remain `unverified` or `needs_review` and require human review.
- Model output varies. Failed notes are retried, and unresolved failures are named in the ready draft.
- Sessions, load checkpoints, and conversation memory are in process and disappear on server restart.
- General questions send all note passages to the model unless direct citation markers narrow the evidence.
  Larger cases need a more selective retrieval strategy.
- The clinician accepts or rejects model-proposed correction text. There is no direct draft-text editor.
- The app has no speech input or output and is not HIPAA-compliant or production-grade.
