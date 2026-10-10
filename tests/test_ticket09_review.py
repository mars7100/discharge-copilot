"""Review regression (ticket 09): a blank canonical name from the model is not a problem; the label stays unmapped."""
from core import llm, problems
from core.models import ClinicalEvent


def test_blank_canonical_name_is_treated_as_unmapped(monkeypatch):
    monkeypatch.setattr(llm, "parse", lambda schema, messages, timeout: problems.ProblemList(
        problems=[problems.Problem(name=" ", labels=["CAP"], conflict_ids=[])]))
    e = ClinicalEvent(event_id="E01", date_or_hospital_day="Hospital Day 1", category="treatment_documented",
                      statement="x", problem="CAP", evidence=[{"span_id": "s1", "quote": "x"}])
    events, order, _, warnings = problems.normalize([e], [])
    assert [x.problem for x in events] == ["CAP"] and order == ["CAP", "Other"]
    assert any("CAP" in w and "unmapped" in w for w in warnings)
