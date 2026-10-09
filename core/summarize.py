"""Validated events -> cited discharge-summary Draft via one LLM call (spec §7.3, §7.4)."""
from pydantic import BaseModel

from core import llm
from core.models import ClinicalEvent, Discrepancy, Draft, SourceSpan, SummaryClaim

SYSTEM = """You draft a discharge summary for a synthetic hospitalization from extracted, documented events.
- Use only the supplied events. No general medical knowledge, no rationale or detail the events do not state.
- One documented fact per claim, one or two short sentences. Hospital course claims in chronological order.
- evidence_span_ids: copy span IDs exactly from the evidence of the events the claim is based on.
- Sections: reason_for_admission, hospital_course, key_events (tests/interventions/documented changes), condition_at_discharge, follow_up, pending_items. Omit a section if nothing is documented for it.
- If events conflict (needs_review), state both documented values with their sources and do not resolve or explain the conflict.
- claim_id any placeholder; clinician_clarification_ids empty; support_status "unverified"."""


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


def generate_draft(events: list[ClinicalEvent], spans: dict[str, SourceSpan]) -> tuple[Draft, list[str]]:
    """Returns (draft, final-attempt validation errors). Retries once on errors or exceptions."""
    lines = [f"{e.event_id} | {e.date_or_hospital_day} | {e.category}{' | NEEDS_REVIEW' if e.needs_review else ''} | "
             f"{e.statement} | spans: {', '.join(r.span_id for r in e.evidence)}" for e in events]
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Events:\n" + "\n".join(lines)}]
    claims, errors = [], []
    for attempt in range(2):
        try:
            result = llm.parse(SummaryResult, messages)
        except Exception as e:
            if not attempt:
                continue
            if not claims:
                raise SummaryError(f"LLM call failed: {e}") from e
            errors = errors + [f"retry failed: {e}"]
            break
        numbered = [c.model_copy(update={"claim_id": f"C{i:02d}", "clinician_clarification_ids": []})
                    for i, c in enumerate(result.claims, 1)]
        claims, errors = check_claims(numbered, spans)
        if not errors:
            break
        if not attempt:
            messages = messages + [
                {"role": "assistant", "content": SummaryResult(claims=numbered).model_dump_json()},
                {"role": "user", "content": "Validation errors:\n" + "\n".join(errors) + "\nReturn a corrected full result."}]
    if not claims:
        raise SummaryError("no valid claims: " + "; ".join(errors))
    flagged = [e for e in events if e.needs_review]
    review_sets = [{r.span_id for r in e.evidence} for e in flagged]  # claim must cite all spans of a flagged event
    claims = [c.model_copy(update={"support_status": "needs_review"
                                   if any(s <= set(c.evidence_span_ids) for s in review_sets) else "unverified"})
              for c in claims]
    discrepancies = [Discrepancy(discrepancy_id=f"D{i:02d}", description=e.statement,
                                 source_span_ids=[r.span_id for r in e.evidence]) for i, e in enumerate(flagged, 1)]
    return Draft(claims=claims, discrepancies=discrepancies), errors
