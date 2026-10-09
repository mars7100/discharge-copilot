"""Clinician corrections: propose -> accept/reject; nothing changes before accept (spec §8.3)."""
from core.models import ClinicianClarification, Draft, ProposedRevision


def propose(draft: Draft, claim_id: str, after: str, statement: str, n: int) -> tuple[ProposedRevision, ClinicianClarification]:
    claim = next(c for c in draft.claims if c.claim_id == claim_id)
    clar = ClinicianClarification(clarification_id=f"K{n:02d}", statement=statement, target_claim_id=claim_id)
    rev = ProposedRevision(revision_id=f"R{n:02d}", target_claim_id=claim_id, before=claim.text, after=after,
                           clinician_statement=statement, clarification_id=clar.clarification_id,
                           source_span_ids=claim.evidence_span_ids)
    return rev, clar


def accept(draft: Draft, rev: ProposedRevision) -> Draft:
    """Apply text, keep document evidence, link clarification, reset approval (T08, T10)."""
    claims = [c.model_copy(update={"text": rev.after,
                                   "clinician_clarification_ids": c.clinician_clarification_ids + [rev.clarification_id]})
              if c.claim_id == rev.target_claim_id else c for c in draft.claims]
    cited = set(rev.source_span_ids)
    discrepancies = [d.model_copy(update={"status": "clarified_pending_approval"}) if cited & set(d.source_span_ids) else d
                     for d in draft.discrepancies]
    return draft.model_copy(update={"claims": claims, "discrepancies": discrepancies,
                                    "status": "draft", "approved_at": None, "reviewer": None})
