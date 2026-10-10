"""Validated events -> cited discharge-summary Draft, one LLM call per template section (spec §7.3, §7.4)."""
from pydantic import BaseModel

from core import llm
from core.models import TEMPLATE, ClinicalEvent, Draft, Resolution, SourceSpan, SummaryClaim

SYSTEM = """You draft a discharge summary for a synthetic hospitalization from extracted, documented events.
- Use only the supplied events. No general medical knowledge, no rationale or detail the events do not state.
- One documented fact per claim, one or two short sentences. Hospital course claims in chronological order.
- evidence_span_ids: copy span IDs exactly from the evidence of the events the claim is based on.
- You draft one section only. Include only the facts that belong in it; if the events state nothing for it, set documented to false and return no claims.
- Resolved facts (lines starting with a D ID) are clinician-provided: state each as written, cite its spans, and put its ID in clinician_clarification_ids. Never mention the superseded values as unresolved.
- claim_id any placeholder; clinician_clarification_ids empty except for resolved facts; support_status "unverified"."""
TIMEOUT = 35


class SectionResult(BaseModel):
    documented: bool
    claims: list[SummaryClaim]


class SummaryError(Exception):
    pass


def check_claims(claims: list[SummaryClaim], spans: dict[str, SourceSpan]) -> tuple[list[SummaryClaim], list[str]]:
    """Keep only cited span IDs that exist; drop claims left with none."""
    valid, errors = [], []
    for c in claims:
        ids = [s for s in c.evidence_span_ids if s in spans]
        errors += [f"{c.claim_id}: unknown span_id {s}" for s in c.evidence_span_ids if s not in spans]
        if ids:
            valid.append(c.model_copy(update={"evidence_span_ids": ids}))
        else:
            errors.append(f"{c.claim_id}: no valid evidence, claim excluded")
    return valid, errors


def draft_section(section_id: str, events: list[ClinicalEvent], spans: dict[str, SourceSpan],
                  resolutions: list[Resolution] = ()) -> dict:
    """One section's {documented, claims (placeholder IDs), warnings}. Retries once on errors or exceptions."""
    purpose = next(s["purpose"] for s in TEMPLATE if s["section_id"] == section_id)
    lines = [f"{e.event_id} | {e.date_or_hospital_day} | {e.category} | {e.statement} | "
             f"spans: {', '.join(r.span_id for r in e.evidence)}" for e in events]
    lines += [f"{r.conflict_id} | RESOLVED (clinician-provided) | {r.text} | spans: {', '.join(q.span_id for q in r.quotes)}"
              for r in resolutions]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Section: {section_id} ({purpose}). Every claim's section is {section_id}.\n"
                                            "Events:\n" + "\n".join(lines)}]
    known = {r.conflict_id for r in resolutions}
    result, claims, errors = None, [], []
    for attempt in range(2):
        try:
            result = llm.parse(SectionResult, messages, TIMEOUT)
        except Exception as e:
            if not attempt:
                continue
            raise SummaryError(f"{section_id}: LLM call failed: {e}") from e
        if not result.documented:
            return {"documented": False, "claims": [], "warnings": []}
        claims, errors = check_claims(result.claims, spans)
        errors += [f"{c.claim_id}: section {c.section}, expected {section_id}, claim excluded" for c in claims if c.section != section_id]
        claims = [c for c in claims if c.section == section_id]
        errors += [f"{c.claim_id}: unknown clinician_clarification_id {i}, removed" for c in claims
                   for i in c.clinician_clarification_ids if i not in known]
        claims = [c.model_copy(update={"clinician_clarification_ids": [i for i in c.clinician_clarification_ids if i in known]})
                  for c in claims]
        if not errors:
            break
        if not attempt:
            messages = messages + [{"role": "assistant", "content": result.model_dump_json()},
                                   {"role": "user", "content": "Validation errors:\n" + "\n".join(errors) + "\nReturn a corrected full result."}]
    if result.claims and not claims:
        raise SummaryError(f"{section_id}: no valid claims: " + "; ".join(errors))
    warnings = [f"{section_id}: {e}" for e in errors]
    if not result.claims:
        warnings.append(f"{section_id}: documented but no claims")
    return {"documented": True, "claims": claims, "warnings": warnings}


def assemble(recs: list[dict], resolutions: list[Resolution]) -> tuple[Draft, list[str]]:
    """Joins section records in template order: numbers claims, adds resolution quotes, states uncarried resolutions."""
    by_section = {r["section_id"]: r for r in recs}
    recs = [by_section[s["section_id"]] for s in TEMPLATE if s["section_id"] in by_section]
    claims = {r["section_id"]: list(r["claims"]) for r in recs}
    warnings = [w for r in recs for w in r["warnings"]]
    for r in resolutions:
        if not any(r.conflict_id in c.clinician_clarification_ids for cs in claims.values() for c in cs):
            warnings.append(f"{r.conflict_id}: resolution not carried by any claim, added to hospital_course")
            claims["hospital_course"].append(SummaryClaim(
                claim_id="x", section="hospital_course", text=r.text, support_status="needs_review",
                evidence_span_ids=list(dict.fromkeys(q.span_id for q in r.quotes)), clinician_clarification_ids=[r.conflict_id]))
    by_id = {r.conflict_id: r for r in resolutions}
    out = []
    for c in (c for cs in claims.values() for c in cs):
        quoted = [q.span_id for i in c.clinician_clarification_ids for q in by_id[i].quotes]
        out.append(c.model_copy(update={"claim_id": f"C{len(out) + 1:02d}",
                                        "evidence_span_ids": list(dict.fromkeys(c.evidence_span_ids + quoted)),
                                        "support_status": "needs_review" if quoted else "unverified"}))
    return Draft(claims=out), warnings
