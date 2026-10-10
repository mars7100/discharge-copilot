import json

import pytest

from core import llm
from core.extract import ExtractionError, ExtractionResult, extract_events
from core.models import ClinicalEvent, Document, SourceSpan

DOCS = [Document(document_id="note_01", filename="note_01.txt", date="2026-03-02", hospital_day=1,
                 type="Admission note", author_role=None)]
SPANS = {sid: SourceSpan(span_id=sid, document_id="note_01", filename="note_01.txt", page=1, order=i, text=t)
         for i, (sid, t) in enumerate([("note_01_p01_b01", "Temperature 38.9 C."),
                                       ("note_01_p01_b02", "Chest X-ray shows right lower lobe consolidation.")], 1)}
GOOD = ("note_01_p01_b02", "right lower lobe consolidation")
BAD = ("note_01_p01_b01", "Temperature 40 C.")


def ev(eid, *refs):
    return ClinicalEvent(event_id=eid, date_or_hospital_day="Hospital Day 1", category="presentation",
                         statement="s", evidence=[{"span_id": s, "quote": q} for s, q in refs])


def stub(monkeypatch, *responses):
    """Each response: list of events, or an Exception to raise. Records messages of every call."""
    calls = []

    def parse(schema, messages, timeout):
        assert schema is ExtractionResult and timeout == 35
        calls.append(messages)
        r = responses[min(len(calls), len(responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return ExtractionResult(events=r)

    monkeypatch.setattr(llm, "parse", parse)
    return calls


def test_single_call_with_all_span_ids_and_renumbered_ids(monkeypatch):
    calls = stub(monkeypatch, [ev("x9", GOOD), ev("foo", GOOD)])
    events, warnings = extract_events(DOCS, SPANS)
    assert len(calls) == 1 and warnings == []
    assert [e.event_id for e in events] == ["E01", "E02"]
    user = " ".join(str(m["content"]) for m in calls[0] if m["role"] == "user")
    assert all(sid in user for sid in SPANS)


def test_retry_once_with_errors_then_valid_only_and_final_warnings(monkeypatch):
    calls = stub(monkeypatch, [ev("a", BAD)], [ev("a", GOOD), ev("b", ("note_01_p01_b09", "x"))])
    events, warnings = extract_events(DOCS, SPANS)
    assert len(calls) == 2
    first, second = calls
    assert second[:len(first)] == first and len(second) > len(first)
    assert "note_01_p01_b01" in json.dumps(second[len(first):])  # first attempt's error fed back
    assert [e.event_id for e in events] == ["E01"] and events[0].evidence[0].start is not None
    assert warnings and any("note_01_p01_b09" in w for w in warnings)


def test_never_more_than_two_calls_and_zero_valid_raises(monkeypatch):
    calls = stub(monkeypatch, [ev("a", BAD)])
    with pytest.raises(ExtractionError):
        extract_events(DOCS, SPANS)
    assert len(calls) == 2


def test_exception_retried_once_then_extraction_error(monkeypatch):
    calls = stub(monkeypatch, RuntimeError("boom"), [ev("a", GOOD)])
    assert len(extract_events(DOCS, SPANS)[0]) == 1 and len(calls) == 2
    calls = stub(monkeypatch, RuntimeError("boom"))
    with pytest.raises(ExtractionError):
        extract_events(DOCS, SPANS)
    assert len(calls) == 2


@pytest.mark.live
def test_case_001_live(case_copy):
    events, warnings = case_copy.events, case_copy.extract_warnings
    assert not any("retry failed" in w for w in warnings), warnings  # e.g. missing retry recording
    assert len(events) >= 3
    assert len({e.date_or_hospital_day for e in events}) >= 3
    assert all(r.start is not None for e in events for r in e.evidence)


def test_retry_exception_keeps_first_attempt_results(monkeypatch):
    calls = stub(monkeypatch, [ev("a", GOOD), ev("b", BAD)], RuntimeError("boom"))
    events, warnings = extract_events(DOCS, SPANS)
    assert len(calls) == 2
    assert [e.event_id for e in events] == ["E01"]
    assert any("E02" in w and "note_01_p01_b01" in w for w in warnings)
    assert any("retry failed" in w for w in warnings)


def test_retry_exception_with_no_valid_first_attempt_raises(monkeypatch):
    stub(monkeypatch, [ev("a", BAD)], RuntimeError("boom"))
    with pytest.raises(ExtractionError):
        extract_events(DOCS, SPANS)


def test_retry_feedback_uses_renumbered_ids(monkeypatch):
    calls = stub(monkeypatch, [ev("x9", GOOD), ev("foo", BAD)], [ev("a", GOOD)])
    extract_events(DOCS, SPANS)
    replayed = " ".join(m["content"] for m in calls[1][len(calls[0]):] if m["role"] == "assistant")
    assert "E01" in replayed and "E02" in replayed
    assert "x9" not in replayed and "foo" not in replayed
