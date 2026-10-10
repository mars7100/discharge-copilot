"""Clinician corrections: propose -> accept/reject; nothing changes before accept (spec §8.3)."""
from pydantic import BaseModel

from core import llm
from core.models import ClinicianClarification, Draft, ProposedRevision, SourceSpan

SYSTEM = """You rewrite one claim of a hospital discharge summary to apply a clinician's correction.
- Change only what the statement corrects; keep the rest of the claim's wording.
- Use no fact that is in neither the statement nor the cited passages.
- Answer in one or two sentences, with no commentary.
- The statement is provided by the clinician and takes precedence over the passages where they disagree."""
TIMEOUT = 20


class CorrectionResult(BaseModel):
    after: str


def rewrite(claim, spans: dict[str, SourceSpan], statement: str) -> str | None:
    """The model's rewritten claim text, or None if blank/unchanged after one retry. Raises if the retry raises."""
    passages = "\n".join(f"[{i}] {spans[i].text}" for i in claim.evidence_span_ids if i in spans)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content":
                f"Section: {claim.section}\nClaim: {claim.text}\nCited passages:\n{passages}\nClinician statement: {statement}"}]
    for attempt in range(2):
        try:
            result = llm.parse(CorrectionResult, messages, TIMEOUT)
        except Exception:
            if attempt:
                raise
            continue
        after = result.after.strip()
        if after and after != claim.text.strip():
            return after
        if not attempt:
            messages = messages + [{"role": "assistant", "content": result.model_dump_json()},
                                   {"role": "user", "content": "The result is blank or identical to the current claim. Apply the clinician's statement and return the changed text."}]
    return None


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
