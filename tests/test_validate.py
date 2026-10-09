from core.models import ClinicalEvent, EvidenceRef, SourceSpan
from core.validate import check_events, locate_quote

TEXT = "3. Hypertension: Medication A  10 mg\n daily continued."
SPANS = {sid: SourceSpan(span_id=sid, document_id=sid[:7], filename=sid[:7] + ".txt", page=1, order=i, text=t)
         for i, (sid, t) in enumerate([("note_04_p01_b07", TEXT),
                                       ("note_05_p01_b02", "Patient walking in hallway on room air."),
                                       ("note_06_p01_b03", "Discharged home.")], 1)}


def event(eid, *refs):
    return ClinicalEvent(event_id=eid, date_or_hospital_day="Hospital Day 3", category="other",
                         statement="s", evidence=[EvidenceRef(span_id=s, quote=q) for s, q in refs])


def test_locate_whitespace_insensitive_returns_original_offset():
    assert locate_quote("Medication A 10 mg daily continued.", TEXT) == 17
    assert locate_quote("  Medication A 10\tmg   daily ", TEXT) == 17


def test_locate_rejects_paraphrase_case_change_and_empty():
    assert locate_quote("Medication A 10 mg once daily continued.", TEXT) is None
    assert locate_quote("medication a 10 mg daily continued.", TEXT) is None
    assert locate_quote("", TEXT) is None
    assert locate_quote("   \n", TEXT) is None


def test_unknown_span_and_quote_from_other_span_rejected():
    ok = ("note_04_p01_b07", "Medication A 10 mg")
    events, errors = check_events([event("E01", ok, ("note_99_p01_b01", "Medication A")),
                                   event("E02", ok, ("note_06_p01_b03", "walking in hallway"))], SPANS)
    assert [len(e.evidence) for e in events] == [1, 1]
    assert len(errors) == 2
    assert any("E01" in e and "note_99_p01_b01" in e for e in errors)
    assert any("E02" in e and "note_06_p01_b03" in e for e in errors)


def test_mixed_evidence_keeps_valid_with_start_and_empty_event_excluded():
    good = event("E01", ("note_04_p01_b07", "Medication A 10 mg"), ("note_04_p01_b07", "not in text"),
                 ("note_05_p01_b02", "room air."))
    bad = event("E02", ("note_06_p01_b03", "Admitted."))
    events, errors = check_events([good, bad], SPANS)
    assert [e.event_id for e in events] == ["E01"]
    assert [(r.span_id, r.start) for r in events[0].evidence] == [("note_04_p01_b07", 17), ("note_05_p01_b02", 30)]
    assert any("E02" in e for e in errors)


def test_inputs_not_mutated():
    ev = event("E01", ("note_04_p01_b07", "Medication A 10 mg"), ("note_99_p01_b01", "x"))
    before = ev.model_dump()
    check_events([ev], SPANS)
    assert ev.model_dump() == before and ev.evidence[0].start is None


def test_locate_treats_regex_metacharacters_literally():
    assert locate_quote("10 mg (daily)", "x 10 mg (daily)") == 2
    assert locate_quote("10 mg (daily)", "x 10 mg daily") is None
