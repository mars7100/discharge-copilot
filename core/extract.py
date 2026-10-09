"""Documents + spans -> evidence-linked ClinicalEvents via one LLM call (spec §7.2)."""
from pydantic import BaseModel

from core import llm
from core.models import ClinicalEvent, Document, SourceSpan
from core.validate import check_events

SYSTEM = """You extract clinical events from synthetic hospital notes.
- Extract only clinical events documented in the supplied notes. No inference, no general medical knowledge, no rationale that the notes do not state.
- Each evidence item cites one span: span_id exactly as given, and quote copied verbatim from that span (a sentence or clause, not the whole span). Set start to null.
- event_id may be any placeholder; it is renumbered afterwards.
- date_or_hospital_day: use the note's documented date/hospital day, e.g. "2026-03-04 (Hospital Day 3)".
- One documented fact per event; never combine unrelated facts in one event.
- For each hospital day, include vital-sign status and medication status when documented.
- Set needs_review to true when the notes document conflicting values for the same fact in an overlapping or unclear time period.
- Report each conflict as exactly one needs_review event citing one passage from each conflicting note; do not set needs_review on any other event."""


class ExtractionResult(BaseModel):
    events: list[ClinicalEvent]


class ExtractionError(Exception):
    pass


def extract_events(documents: list[Document], spans: dict[str, SourceSpan]) -> tuple[list[ClinicalEvent], list[str]]:
    """Returns (valid events, final-attempt validation errors). Retries once on errors or exceptions."""
    docs = "\n".join(f"{d.document_id} | date {d.date} | hospital day {d.hospital_day} | {d.type}" for d in documents)
    notes = "\n".join(f"[{s.span_id}] {s.text}" for s in spans.values())
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Documents:\n{docs}\n\nSpans:\n{notes}"}]
    events, errors = [], []
    for attempt in range(2):
        try:
            result = llm.parse(ExtractionResult, messages)
        except Exception as e:
            if attempt:
                if not events:
                    raise ExtractionError(f"LLM call failed twice: {e}") from e
                errors.append(f"retry failed: {e}")
                break
            continue
        numbered = [e.model_copy(update={"event_id": f"E{i:02d}"}) for i, e in enumerate(result.events, 1)]
        events, errors = check_events(numbered, spans)
        if not errors:
            break
        if not attempt:
            messages = messages + [
                {"role": "assistant", "content": ExtractionResult(events=numbered).model_dump_json()},
                {"role": "user", "content": "Validation errors:\n" + "\n".join(errors)
                 + "\nReturn a corrected full result."}]
    if not events:
        raise ExtractionError("no valid events extracted: " + "; ".join(errors))
    return events, errors
