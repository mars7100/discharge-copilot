"""Validated events -> cited discharge-summary Draft via one LLM call (spec §7.3, §7.4)."""
from pydantic import BaseModel

from core import llm
from core.models import TEMPLATE, ClinicalEvent, Draft, Resolution, SourceSpan, SummaryClaim

SYSTEM = """You draft a discharge summary for a synthetic hospitalization from extracted, documented events.
- Use only the supplied events. No general medical knowledge, no rationale or detail the events do not state.
- One documented fact per claim, one or two short sentences. Hospital course claims in chronological order.
- evidence_span_ids: copy span IDs exactly from the evidence of the events the claim is based on.
- Sections: """ + ", ".join(f"{s['section_id']} ({s['purpose']})" for s in TEMPLATE) + """. Omit a section if nothing is documented for it.
- Resolved facts (lines starting with a D ID) are clinician-provided: state each as written, cite its spans, and put its ID in clinician_clarification_ids. Never mention the superseded values as unresolved.
- claim_id any placeholder; clinician_clarification_ids empty except for resolved facts; support_status "unverified"."""
TIMEOUT = 35


class SummaryResult(BaseModel):
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


def generate_draft(events: list[ClinicalEvent], spans: dict[str, SourceSpan],
                   resolutions: list[Resolution] = ()) -> tuple[Draft, list[str]]:
    """Returns (draft, final-attempt validation errors). Retries once on errors or exceptions."""
    lines = [f"{e.event_id} | {e.date_or_hospital_day} | {e.category} | {e.statement} | "
             f"spans: {', '.join(r.span_id for r in e.evidence)}" for e in events]
    lines += [f"{r.conflict_id} | RESOLVED (clinician-provided) | {r.text} | spans: {', '.join(q.span_id for q in r.quotes)}"
              for r in resolutions]
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Events:\n" + "\n".join(lines)}]
    known = {r.conflict_id for r in resolutions}
    claims, errors = [], []
    for attempt in range(2):
        try:
            result = llm.parse(SummaryResult, messages, TIMEOUT)
        except Exception as e:
            if not attempt:
                continue
            if not claims:
                raise SummaryError(f"LLM call failed: {e}") from e
            errors = errors + [f"retry failed: {e}"]
            break
        numbered = [c.model_copy(update={"claim_id": f"C{i:02d}"}) for i, c in enumerate(result.claims, 1)]
        claims, errors = check_claims(numbered, spans)
        errors += [f"{c.claim_id}: unknown clinician_clarification_id {i}, removed" for c in claims
                   for i in c.clinician_clarification_ids if i not in known]
        claims = [c.model_copy(update={"clinician_clarification_ids": [i for i in c.clinician_clarification_ids if i in known]})
                  for c in claims]
        errors += [f"{r.conflict_id}: resolution not carried by any claim (set clinician_clarification_ids)"
                   for r in resolutions if not any(r.conflict_id in c.clinician_clarification_ids for c in claims)]
        if not errors:
            break
        if not attempt:
            messages = messages + [
                {"role": "assistant", "content": SummaryResult(claims=numbered).model_dump_json()},
                {"role": "user", "content": "Validation errors:\n" + "\n".join(errors) + "\nReturn a corrected full result."}]
    if not claims:
        raise SummaryError("no valid claims: " + "; ".join(errors))
    by_id = {r.conflict_id: r for r in resolutions}
    out = []
    for c in claims:
        quoted = [q.span_id for i in c.clinician_clarification_ids for q in by_id[i].quotes]
        out.append(c.model_copy(update={"evidence_span_ids": list(dict.fromkeys(c.evidence_span_ids + quoted)),
                                        "support_status": "needs_review" if quoted else "unverified"}))
    for r in resolutions:  # the model dropped it twice: code states the resolution itself
        if not any(r.conflict_id in c.clinician_clarification_ids for c in out):
            out.append(SummaryClaim(claim_id=f"C{len(out) + 1:02d}", section="hospital_course", text=r.text,
                                    evidence_span_ids=list(dict.fromkeys(q.span_id for q in r.quotes)),
                                    clinician_clarification_ids=[r.conflict_id], support_status="needs_review"))
    return Draft(claims=out), errors
