from core.export import NOT_DOCUMENTED, to_markdown
from core.models import Draft, SourceSpan, SummaryClaim

SPAN = SourceSpan(span_id="note_04_p01_b07", document_id="note_04", filename="note_04.txt",
                  page=1, order=7, text="Medication A 10 mg daily.")


def test_empty_required_sections_say_not_documented_and_empty_optional_ones_are_omitted():
    claim = SummaryClaim(claim_id="C01", section="discharge_medications", text="Medication A 10 mg daily.",
                         evidence_span_ids=[SPAN.span_id], support_status="unverified")
    md = to_markdown(Draft(claims=[claim]), {SPAN.span_id: SPAN}, [])
    headings = [line for line in md.splitlines() if line.startswith("## ")][:5]
    assert headings == ["## Reason for admission", "## Hospital course", "## Condition at discharge",
                        "## Discharge medications", "## Follow-up"]
    assert md.count(NOT_DOCUMENTED) == 4
