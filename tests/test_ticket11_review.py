"""Review regression (ticket 11): the existing problems passed as `known` decide the case-insensitive join, not the raw labels."""
from core import llm, problems
from core.models import ClinicalEvent


def test_mapped_label_joins_known_problem_and_canonical_names_are_kept(monkeypatch):
    def event(label):
        return ClinicalEvent(event_id="E01", date_or_hospital_day="Hospital Day 1", category="treatment_documented",
                             statement="x", problem=label, evidence=[{"span_id": "s1", "quote": "x"}])
    monkeypatch.setattr(llm, "parse", lambda schema, messages, timeout: problems.ProblemList(
        problems=[problems.Problem(name="pneumonia", labels=["pneumonia"], conflict_ids=[])]))
    events, _, _, _ = problems.normalize([event("pneumonia")], [], ["Pneumonia"])
    assert [e.problem for e in events] == ["Pneumonia"]  # joins the existing problem, whatever the model's case

    monkeypatch.setattr(llm, "parse", lambda schema, messages, timeout: problems.ProblemList(
        problems=[problems.Problem(name="CAP", labels=["cap"], conflict_ids=[])]))
    events, _, _, _ = problems.normalize([event("cap")], [])
    assert [e.problem for e in events] == ["CAP"]  # no known problems: the model's canonical name stands
