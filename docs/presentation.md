# DischargeCopilot — 3-minute presentation (6 slides)

Format and timing from the kickoff deck ("Three minutes, six slides"). Total: 180 s including the demo.
Items marked **[confirm]** are placeholders or assumptions to verify before presenting.

---

## Slide 1 — Introduction (10 s)

**DischargeCopilot**
An API-first AI copilot that turns clinical notes into source-linked discharge summaries.

- Team Axel: Axel (solo)
- Visual: `docs/logo/logo-full.png`

> Speaker: "I'm Axel, and this is DischargeCopilot."

---

## Slide 2 — Problem (25 s)

**Residents read every progress note to write one discharge summary.**

- Challenge from Paul Cordero Villarrubia, resident physician
- A hospital stay produces many notes, and they sometimes disagree (doses, dates, follow-up)
- Writing the summary by hand is slow; an unchecked AI summary is unsafe
- Puerto Rico physicians fell from 18,754 (2009) to 9,492 (2022): PR Health Department undersecretary, via [News is my Business, May 2022](https://newsismybusiness.com/50-of-doctors-have-left-puerto-rico-since-09)
- 35 of 41 PR hospitals had 30-day readmission rates above the U.S. average of 15.3%: V2A Consulting on CMS Hospital Compare, via [News is my Business, Dec 2019](https://newsismybusiness.com/study-p-r-hospitals-show-higher-readmission-mortality-rates-vs-u-s-peers)

> Speaker: "The hard part isn't shortening text. It's keeping every detail, showing where it came from, and making conflicts visible."

---

## Slide 3 — Proposed solution (30 s)

**Notes in → cited draft → clinician review → approved summary**

1. Reads all notes for one admission and extracts clinical events
2. Finds conflicts between notes and **asks the resident** instead of guessing
3. Drafts each summary section; every claim links to its source passage
4. Resident asks questions, proposes corrections, reviews before/after
5. Resident approves; exports a Word document

Human review at every step: nothing is final until a clinician approves it.

---

## Slide 4 — Demo (75 s)

Main task: from synthetic notes to an approved summary.

1. Load a case **[confirm: which case has a conflict, e.g. case_001]** (~10 s)
2. Resolve a conflict between two notes (~15 s)
3. Open the draft; click a citation to see the source passage (~15 s)
4. Ask a question about the case; show the cited answer (~10 s)
5. Propose a correction in plain words; accept the before/after (~15 s)
6. Approve and download the Word document (~10 s)

Live app: https://dispatch-copilot-z24qhdjsba-uc.a.run.app
Backup demo video: https://youtu.be/m7dsygF2HG4

---

## Slide 5 — Technology (20 s)

**How it works**
- FastAPI backend, API-first: the UI is one client, the same API can back an EHR plugin
- LangGraph pipelines: parallel note extraction and section drafting, pause for conflict resolution
- OpenAI structured outputs; every cited quote is checked word for word against its source
- React + TypeScript UI with streaming; python-docx for Word export

**What's simulated / limitations**
- Synthetic notes only; no real patient data, no EHR integration yet
- Not HIPAA-compliant yet; not clinically validated
- Voice input not in the current UI

---

## Slide 6 — Next steps (20 s)

**Rollout**
- Pilot first with: a residency program, starting with the challenge sponsor's team **[confirm]**
- Needed before rollout: clinician validation on de-identified data, HIPAA compliance, EHR integration

**Future features**
- Batch processing: per patient or in bulk by date range, physician/provider, or medical insurance
- EHR plugin and white label
- Voice interaction
- Plugin store with automations for healthcare professionals

> Speaker: "Thank you. Questions?"

Rendered deck: `docs/deck/DischargeCopilot.pdf` (source `docs/deck/deck.html`).
