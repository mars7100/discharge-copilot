import pytest
from pydantic import ValidationError

from core.models import ClinicalEvent, Draft, SourceSpan, SummaryClaim

SPAN = SourceSpan(span_id="note_04_p01_b07", document_id="note_04", filename="note_04.txt",
                  page=1, order=7, text="3. Hypertension: Medication A 10 mg daily continued.")


def event(**kw):
    base = dict(event_id="E01", date_or_hospital_day="Hospital Day 3", category="treatment_documented",
                statement="Medication A 10 mg daily continued.",
                evidence=[{"span_id": SPAN.span_id, "quote": "Medication A 10 mg daily continued."}])
    return ClinicalEvent(**base | kw)


def claim(**kw):
    base = dict(claim_id="C01", section="key_events", text="Medication A 10 mg daily.",
                evidence_span_ids=[SPAN.span_id], support_status="needs_review")
    return SummaryClaim(**base | kw)


def test_valid_models_build():
    assert event().evidence[0].span_id == SPAN.span_id
    d = Draft(claims=[claim()])
    assert d.status == "draft" and d.approved_at is None


def test_event_requires_evidence():
    with pytest.raises(ValidationError):
        event(evidence=[])


def test_unknown_section_rejected():
    with pytest.raises(ValidationError):
        claim(section="diagnosis")


def test_unknown_category_rejected():
    with pytest.raises(ValidationError):
        event(category="recommendation")
