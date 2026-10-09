from datetime import datetime

from core.models import Discrepancy, Draft, SummaryClaim
from core.revise import accept, propose

DRAFT = Draft(
    claims=[SummaryClaim(claim_id="C01", section="hospital_course", text="Medication A 10 mg vs 5 mg conflicting.",
                         evidence_span_ids=["note_04_p01_b07", "note_05_p01_b04"], support_status="needs_review"),
            SummaryClaim(claim_id="C02", section="follow_up", text="Follow up in 1 week.",
                         evidence_span_ids=["note_06_p01_b09"], support_status="unverified")],
    discrepancies=[Discrepancy(discrepancy_id="D01", description="dose conflict",
                               source_span_ids=["note_04_p01_b07", "note_05_p01_b04"])],
    status="approved", approved_at=datetime(2026, 10, 9), reviewer="Simulated resident")
STATEMENT = "It was 5 mg initially and changed to 10 mg on day three."


def test_propose_does_not_change_draft():  # T06 / T07 (reject = never calling accept)
    before = DRAFT.model_copy(deep=True)
    rev, clar = propose(DRAFT, "C01", "5 mg initially, 10 mg from Day 3.", STATEMENT, 1)
    assert DRAFT == before
    assert (rev.status, rev.before, rev.clinician_statement) == ("pending", DRAFT.claims[0].text, STATEMENT)
    assert clar.clarification_id == rev.clarification_id and clar.status == "pending"


def test_accept_applies_keeps_provenance_and_resets_approval():  # T08 / T10
    rev, clar = propose(DRAFT, "C01", "5 mg initially, 10 mg from Day 3.", STATEMENT, 1)
    new = accept(DRAFT, rev)
    c1 = new.claims[0]
    assert c1.text == "5 mg initially, 10 mg from Day 3."
    assert c1.evidence_span_ids == DRAFT.claims[0].evidence_span_ids  # document evidence retained
    assert c1.clinician_clarification_ids == [clar.clarification_id]
    assert new.claims[1] == DRAFT.claims[1]
    assert new.discrepancies[0].status == "clarified_pending_approval"
    assert (new.status, new.approved_at, new.reviewer) == ("draft", None, None)
