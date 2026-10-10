from core import llm
from core.conflicts import ConflictResult, find_conflicts
from core.models import ConflictItem, Document, SourceSpan

DOCS = [Document(document_id=f"note_0{k}", filename=f"note_0{k}.txt", date=None, hospital_day=k, type=None,
                 author_role=None) for k in (1, 2)]
SPANS = {f"note_0{k}_p01_b01": SourceSpan(span_id=f"note_0{k}_p01_b01", document_id=f"note_0{k}",
                                          filename=f"note_0{k}.txt", page=1, order=1, text=f"Weight {k}0 kg.")
         for k in (1, 2)}


def test_retry_exception_keeps_first_attempt_valid_conflicts(monkeypatch):
    """Like extract_events: a validation retry that raises falls back to the first attempt, it does not fail the load."""
    first = ConflictResult(conflicts=[ConflictItem(conflict_id="x", description="Weight differs", quotes=[
        {"span_id": "note_01_p01_b01", "quote": "Weight 10 kg."}, {"span_id": "note_02_p01_b01", "quote": "Weight 20 kg."},
        {"span_id": "note_09_p01_b01", "quote": "Weight 90 kg."}])])
    responses = [first, RuntimeError("timeout")]

    def parse(schema, messages, timeout):
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(llm, "parse", parse)

    found, warnings = find_conflicts(DOCS, SPANS)
    assert [[q.span_id for q in c.quotes] for c in found] == [["note_01_p01_b01", "note_02_p01_b01"]]
    assert any("note_09_p01_b01" in w for w in warnings) and any("retry failed" in w for w in warnings)
