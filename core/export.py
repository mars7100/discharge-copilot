"""Draft -> Markdown export with source appendix (spec §10 Export output)."""
from datetime import datetime

from core.models import TEMPLATE, ClinicianClarification, Document, Draft, Resolution, SourceSpan

SECTIONS = {s["section_id"]: s["title"] for s in TEMPLATE}
NOT_DOCUMENTED = "Not documented in the supplied notes."


def marker(span: SourceSpan) -> str:
    return f"[N{span.document_id[-2:]}:B{span.order:02d}]"


def to_markdown(draft: Draft, spans: dict[str, SourceSpan], documents: list[Document], case_id: str = "case_001",
                clarifications: list[ClinicianClarification] = (), resolutions: list[Resolution] = (),
                missing_notes: list[str] = ()) -> str:
    status = (f"APPROVED by {draft.reviewer} at {draft.approved_at:%Y-%m-%d %H:%M}" if draft.status == "approved"
              else "DRAFT — NOT APPROVED")
    out = ["# Discharge summary", "", "**SYNTHETIC DEMONSTRATION — NOT FOR CLINICAL USE**", "",
           f"- Case: {case_id} (fictional)", f"- Status: {status}", f"- Generated: {datetime.now():%Y-%m-%d %H:%M}", ""]
    if missing_notes:
        out += [f"**Incomplete: notes not included (extraction failed): {', '.join(missing_notes)}**", ""]
    for section in TEMPLATE:
        claims = [c for c in draft.claims if c.section == section["section_id"]]
        if not claims and section["optional"]:
            continue
        out += [f"## {section['title']}", ""]
        claims.sort(key=lambda c: c.problem is not None)  # corrections without a problem go first, no subheading
        for i, c in enumerate(claims):
            if c.problem and (i == 0 or c.problem != claims[i - 1].problem):
                out.append(f"### {c.problem}")
            flag = " **(needs review)**" if c.support_status == "needs_review" else ""
            clar = " *(clinician-provided)*" if c.clinician_clarification_ids else ""
            out.append(f"- {c.text}{flag}{clar} " + " ".join(marker(spans[s]) for s in c.evidence_span_ids))
        out += ([] if claims else [NOT_DOCUMENTED]) + [""]
    out += ["## Unresolved discrepancies", ""]
    resolved = {r.conflict_id for r in resolutions}
    open_ = [d for d in draft.discrepancies if d.discrepancy_id not in resolved]  # corrections alone do not resolve one
    for d in open_:
        out.append(f"- {d.discrepancy_id} ({d.status}): {d.description} "
                   + " ".join(marker(spans[s]) for s in d.source_span_ids))
    out += ([] if open_ else ["None flagged."]) + ["", "## Conflict resolutions", ""]
    desc = {d.discrepancy_id: d.description for d in draft.discrepancies}
    out += [f"- {r.conflict_id}: {desc.get(r.conflict_id, '')} — \"{r.text}\" (clinician-provided; "
            + (f"chosen from {marker(spans[r.chosen_span_id])}" if r.chosen_span_id else "typed clarification") + ") "
            + " ".join(marker(spans[q.span_id]) for q in r.quotes) for r in resolutions] or ["None."]
    out += ["", "## Clinician-provided clarifications", ""]
    accepted = [k for k in clarifications if k.status == "accepted"]
    out += [f"- {k.clarification_id} → {k.target_claim_id}: \"{k.statement}\" (clinician-provided, not document evidence)"
            for k in accepted] or ["None."]
    out += ["", "## Source appendix", ""]
    files = {d.document_id: d for d in documents}
    cited = {s for c in draft.claims for s in c.evidence_span_ids} | {s for d in draft.discrepancies for s in d.source_span_ids} \
        | {q.span_id for r in resolutions for q in r.quotes}
    for sid in sorted(cited):
        sp = spans[sid]
        doc = files.get(sp.document_id)
        when = f", {doc.date} (Hospital Day {doc.hospital_day})" if doc else ""
        out += [f"**{marker(sp)}** {sp.filename}, page {sp.page}{when}", "", "> " + sp.text.replace("\n", "\n> "), ""]
    return "\n".join(out)
