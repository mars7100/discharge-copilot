"""Documents + spans -> evidence-linked ClinicalEvents via one LLM call (spec §7.2)."""
from pydantic import BaseModel

from core import llm
from core.models import TEMPLATE, ClinicalEvent, Document, SourceSpan
from core.validate import check_events

SYSTEM = """You extract clinical events from synthetic hospital notes.
- Extract only clinical events documented in the supplied notes. No inference, no general medical knowledge, no rationale that the notes do not state.
- Each evidence item cites one span: span_id exactly as given, and quote copied verbatim from that span (a sentence or clause, not the whole span). Set start to null.
- event_id may be any placeholder; it is renumbered afterwards.
- date_or_hospital_day: use the note's documented date/hospital day, e.g. "2026-03-04 (Hospital Day 3)".
- One documented fact per event; never combine unrelated facts in one event.
- For each hospital day, include vital-sign status and medication status when documented.
- Set problem to the clinical problem the event belongs to, as named in the note (e.g. "community-acquired pneumonia"), free text; null if the note names none.
- Set sections to every section below that the event belongs in; [] when it belongs only in the hospital course (the catch-all, always covered by problem). Sections:
""" + "\n".join(f"  {s['section_id']}: {s['purpose']}" for s in TEMPLATE if s["section_id"] != "hospital_course")
TIMEOUT = 35  # one call per note


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
            result = llm.parse(ExtractionResult, messages, TIMEOUT)
        except Exception as e:
            if attempt:
                if not events:
                    raise ExtractionError(f"LLM call failed twice: {e}") from e
                errors.append(f"retry failed: {e}")
                break
            continue
        numbered = [e.model_copy(update={"event_id": f"E{i:02d}", "needs_review": False}) for i, e in enumerate(result.events, 1)]
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
