"""One call over all passages -> cross-note conflicts with verbatim quotes (ticket 06)."""
from pydantic import BaseModel

from core import llm
from core.models import ConflictItem, Document, SourceSpan
from core.validate import locate_quote

SYSTEM = """You compare facts across synthetic hospital notes and report documentation conflicts.
- Report only facts whose documented values disagree for the same or an overlapping time period. Zero conflicts is a valid answer.
- For each conflict: a short description, and one quote from every conflicting passage: span_id exactly as given, quote copied verbatim from that span (a sentence or clause). Set start to null.
- Never resolve or explain a conflict. No inference, no general medical knowledge.
- conflict_id may be any placeholder."""
TIMEOUT = 35


class ConflictResult(BaseModel):
    conflicts: list[ConflictItem]


def check_conflicts(items: list[ConflictItem], spans: dict[str, SourceSpan]) -> tuple[list[ConflictItem], list[str]]:
    """Keep quotes found in their span (start filled); drop conflicts left with fewer than 2."""
    valid, errors = [], []
    for c in items:
        kept = []
        for q in c.quotes:
            span = spans.get(q.span_id)
            if span is None:
                errors.append(f"{c.conflict_id}: unknown span_id {q.span_id}")
            elif (start := locate_quote(q.quote, span.text)) is None:
                errors.append(f"{c.conflict_id}: quote not found in {q.span_id}: {q.quote!r}")
            else:
                kept.append(q.model_copy(update={"start": start}))
        if len(kept) >= 2:
            valid.append(c.model_copy(update={"quotes": kept}))
        else:
            errors.append(f"{c.conflict_id}: fewer than 2 valid quotes, conflict excluded")
    return valid, errors


def find_conflicts(documents: list[Document], spans: dict[str, SourceSpan]) -> tuple[list[ConflictItem], list[str]]:
    """Returns (valid conflicts, final-attempt validation errors). Retries once on errors or exceptions."""
    docs = "\n".join(f"{d.document_id} | date {d.date} | hospital day {d.hospital_day} | {d.type}" for d in documents)
    notes = "\n".join(f"[{s.span_id}] {s.text}" for s in spans.values())
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Documents:\n{docs}\n\nSpans:\n{notes}"}]
    found, errors = [], []
    for attempt in range(2):
        try:
            result = llm.parse(ConflictResult, messages, TIMEOUT)
        except Exception as e:
            if attempt and not errors:  # both calls failed
                raise
            if attempt:  # retry after validation errors failed: keep the first attempt
                errors.append(f"retry failed: {e}")
                break
            continue
        numbered = [c.model_copy(update={"conflict_id": f"D{i:02d}"}) for i, c in enumerate(result.conflicts, 1)]
        found, errors = check_conflicts(numbered, spans)
        if not errors:
            break
        if not attempt:
            messages = messages + [
                {"role": "assistant", "content": ConflictResult(conflicts=numbered).model_dump_json()},
                {"role": "user", "content": "Validation errors:\n" + "\n".join(errors) + "\nReturn a corrected full result."}]
    return found, errors
