"""Discharge Copilot — Streamlit UI (spec §10). Run: .venv/bin/streamlit run app.py"""
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

os.environ.setdefault("LLM_MODE", "replay")  # recorded LLM output: instant, offline, reproducible

from core.export import NOT_DOCUMENTED, SECTIONS, marker, to_markdown  # noqa: E402
from core.extract import extract_events  # noqa: E402
from core.ingest import ingest_dir  # noqa: E402
from core.review_graph import ask  # noqa: E402
from core.revise import accept, propose  # noqa: E402
from core.summarize import generate_draft  # noqa: E402

CASE_DIR = Path(__file__).parent / "fixtures" / "case_001"
ss = st.session_state
APP_KEYS = ("documents", "spans", "ingest_warnings", "events", "extract_warnings", "draft", "summary_warnings",
            "revisions", "clarifications", "pending", "chat", "error")

st.set_page_config(page_title="Discharge Copilot", layout="wide")
st.title("Discharge Copilot")
st.error("SYNTHETIC DATA — DEMO ONLY. Not for clinical use.")


def load_case():
    ss.pop("error", None)  # overwrite app keys only; clearing widget state inside a callback drops clicks
    ss.documents, ss.spans, ss.ingest_warnings = ingest_dir(CASE_DIR)
    ss.revisions, ss.clarifications, ss.pending, ss.chat = [], [], None, []
    try:
        ss.events, ss.extract_warnings = extract_events(ss.documents, ss.spans)
        ss.draft, ss.summary_warnings = generate_draft(ss.events, ss.spans)
    except Exception as e:  # keep documents loaded for retry (spec §10)
        ss.error = str(e)


def source_popovers(span_ids, key):
    row = st.container(horizontal=True)
    for sid in dict.fromkeys(span_ids):
        sp = ss.spans[sid]
        with row.popover(marker(sp), key=f"{key}-{sid}"):
            st.caption(f"`{sp.span_id}` — {sp.filename}, page {sp.page}")
            st.markdown(sp.text.replace("\n", "  \n"))


def resolve(accepted: bool):
    rev, clar = ss.pending
    status = "accepted" if accepted else "rejected"
    if accepted:
        ss.draft = accept(ss.draft, rev)
    ss.revisions.append(rev.model_copy(update={"status": status}))
    ss.clarifications.append(clar.model_copy(update={"status": status}))
    ss.pending = None


with st.sidebar:
    st.button("Load sample case", on_click=load_case, type="primary")
    st.button("Reset session", on_click=lambda: [ss.pop(k) for k in APP_KEYS if k in ss])
    st.caption(f"LLM mode: {os.environ['LLM_MODE']}")

if "documents" not in ss:
    st.info("Status: Not loaded. Use **Load sample case** in the sidebar.")
    st.stop()
if "error" in ss:
    st.error(f"Generation failed: {ss.error}")
    st.stop()

draft, spans = ss.draft, ss.spans
st.subheader(f"Status: {'Approved' if draft.status == 'approved' else 'Draft — pending review'}")
for w in ss.ingest_warnings + ss.extract_warnings + ss.summary_warnings:
    st.warning(w)

open_items = sum(d.status == "open" for d in draft.discrepancies) + bool(ss.pending)
t_sum, t_rev, t_ask, t_src, t_out = st.tabs(["Summary", f"Needs review ({open_items})", "Ask about the notes",
                                             "Sources", "Approve & export"])

with t_sum:
    clar_text = {k.clarification_id: k.statement for k in ss.clarifications}
    for key, title in SECTIONS.items():
        claims = [c for c in draft.claims if c.section == key]
        with st.expander(f"{title} ({len(claims)})", expanded=key in ("reason_for_admission", "condition_at_discharge")):
            if not claims:
                st.caption(NOT_DOCUMENTED)
            for c in claims:
                flag = (" :green[**clarified by clinician — pending approval**]" if c.clinician_clarification_ids
                        else " :orange[**needs review**]") if c.support_status == "needs_review" else ""
                st.markdown(f"`{c.claim_id}` {c.text}{flag}")
                for k in c.clinician_clarification_ids:
                    st.caption(f":blue[Clinician-provided ({k}): “{clar_text.get(k, '')}”]")
                source_popovers(c.evidence_span_ids, c.claim_id)

with t_rev:
    for d in draft.discrepancies:
        with st.container(border=True):
            st.markdown(f"**{d.discrepancy_id}** ({d.status}) — {d.description}")
            for col, sid in zip(st.columns(len(d.source_span_ids)), d.source_span_ids):
                with col.container(border=True):
                    st.caption(f"{marker(spans[sid])} {spans[sid].filename}")
                    st.markdown(spans[sid].text.replace("\n", "  \n"))
    st.markdown("#### Clinician correction")
    if ss.pending:
        rev, _ = ss.pending
        st.markdown(f"**Proposed revision {rev.revision_id}** to `{rev.target_claim_id}` — "
                    ":orange[clinician-provided, pending approval]")
        st.markdown(f"Before: ~~{rev.before}~~")
        st.markdown(f"After: **{rev.after}**")
        st.caption(f"Clinician statement: “{rev.clinician_statement}” · Document evidence kept: "
                   + ", ".join(marker(spans[s]) for s in rev.source_span_ids))
        a, r = st.columns(2)
        a.button("Accept", type="primary", on_click=resolve, args=(True,))
        r.button("Reject", on_click=resolve, args=(False,))
    else:
        ids = [c.claim_id for c in draft.claims]
        default = next((i for i, c in enumerate(draft.claims) if c.support_status == "needs_review"), 0)
        target = st.selectbox("Claim to correct", ids, index=default,
                              format_func=lambda i: f"{i}: {next(c.text for c in draft.claims if c.claim_id == i)[:90]}")
        statement = st.text_input("Clinician statement", "It was 5 mg initially and changed to 10 mg on day three.")
        after = st.text_area("Corrected claim text", next(c.text for c in draft.claims if c.claim_id == target))
        if st.button("Propose correction"):
            ss.pending = propose(draft, target, after, statement, len(ss.revisions) + 1)
            st.rerun()
    for rev in ss.revisions:
        st.caption(f"{rev.revision_id} → {rev.target_claim_id}: {rev.status}")

with t_ask:
    question = st.text_input("Ask about the notes")
    if st.button("Ask") and question.strip():
        try:
            res = ask(question, ss.draft, ss.spans, ss.events)
            ss.chat.append((question, res["intent"], res["answer"], res["cited"]))
        except Exception as e:
            st.error(f"Question failed: {e}")
    for i, (q, _intent, ans, cited) in reversed(list(enumerate(ss.chat))):
        with st.container(border=True):
            st.markdown(f"**{q}**")
            st.markdown(ans)
            if cited:
                st.caption("What the notes state")
                source_popovers(cited, key=f"qa{i}")

with t_src:
    for doc in ss.documents:
        with st.expander(f"{doc.document_id} — {doc.date} (Day {doc.hospital_day}) — {doc.type}"):
            for sp in (sp for sp in spans.values() if sp.document_id == doc.document_id):
                st.caption(f"{marker(sp)} · page {sp.page}")
                st.markdown(sp.text.replace("\n", "  \n"))

with t_out:
    if draft.status != "approved":
        if ss.pending:
            st.info("Accept or reject the pending correction before approving.")
        reviewer = st.text_input("Simulated reviewer label", "Simulated resident (demo)")
        if st.button("Approve draft", type="primary", disabled=bool(ss.pending)):
            ss.draft = draft.model_copy(update={"status": "approved", "approved_at": datetime.now(),
                                                "reviewer": reviewer})
            st.rerun()
    else:
        st.success(f"Approved by {draft.reviewer} at {draft.approved_at:%Y-%m-%d %H:%M}")
    md = to_markdown(ss.draft, spans, ss.documents, clarifications=ss.clarifications)
    st.download_button("Export Markdown" + ("" if ss.draft.status == "approved" else " (unapproved draft)"),
                       md, file_name="discharge_summary_case_001.md")
    with st.expander("Preview export"):
        st.markdown(md)
