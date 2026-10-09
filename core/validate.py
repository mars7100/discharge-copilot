"""Cross-object checks: evidence quotes must exist verbatim in their cited spans (spec §7.2)."""
import re

from core.models import ClinicalEvent, SourceSpan


def locate_quote(quote: str, text: str) -> int | None:
    """Offset of quote in text; whitespace-insensitive, case-sensitive, otherwise exact."""
    words = quote.split()
    if not words:
        return None
    m = re.search(r"\s+".join(map(re.escape, words)), text)
    return m.start() if m else None


def check_events(events: list[ClinicalEvent], spans: dict[str, SourceSpan]) -> tuple[list[ClinicalEvent], list[str]]:
    """Keep evidence whose quote is found in its span (start filled); drop events left with none."""
    valid, errors = [], []
    for e in events:
        kept = []
        for r in e.evidence:
            span = spans.get(r.span_id)
            if span is None:
                errors.append(f"{e.event_id}: unknown span_id {r.span_id}")
            elif (start := locate_quote(r.quote, span.text)) is None:
                errors.append(f"{e.event_id}: quote not found in {r.span_id}: {r.quote!r}")
            else:
                kept.append(r.model_copy(update={"start": start}))
        if kept:
            valid.append(e.model_copy(update={"evidence": kept}))
        else:
            errors.append(f"{e.event_id}: no valid evidence, event excluded")
    return valid, errors
