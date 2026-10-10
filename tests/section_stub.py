"""Shared stub helpers for ticket 08 (per-section drafting), used by the core.llm.parse stubs of tickets 03a/06/07/08.

Test-imposed assumptions (the 08 contract leaves the schema name and prompt wording open):
- A section drafting call's structured-output schema has a `documented` field (and a `claims` list whose items accept
  the SummaryClaim fields section, text, evidence_span_ids, clinician_clarification_ids).
- The messages of a section call, before any assistant turn, name exactly one template section_id: the section drafted.
"""
import re

from core.extract import ExtractionResult
from core.models import TEMPLATE, ConflictItem

IDS = [s["section_id"] for s in TEMPLATE]
OPTIONAL = {s["section_id"] for s in TEMPLATE if s["optional"]}
SECTION_EVENTS = ("section_drafted", "section_omitted")


def kind(schema) -> str:
    if schema is ExtractionResult:
        return "extract"
    if "documented" in schema.model_fields:
        return "summary"
    if any(f.annotation == list[ConflictItem] for f in schema.model_fields.values()):
        return "conflict"
    raise AssertionError(f"unexpected schema {schema.__name__}: ticket 08 drafts each section with a schema that has "
                         "a `documented` field")


def section_of(messages) -> str:
    initial = []
    for m in messages:
        if m["role"] == "assistant":
            break
        initial.append(str(m["content"]))
    found = [s for s in IDS if re.search(rf"\b{s}\b", "\n".join(initial))]
    assert len(found) == 1, f"a section call must name exactly one template section_id before any retry, found {found}"
    return found[0]


def section_result(schema, documented: bool, claims=()):
    """claims: dicts with section, text, evidence_span_ids[, clinician_clarification_ids]."""
    return schema.model_validate({"documented": documented, "claims": [
        {"claim_id": "x", "clinician_clarification_ids": [], "support_status": "unverified", **c} for c in claims]})


def collapse(names: list[str]) -> list[str]:
    """One section event per template section (any order, contiguous) collapsed into one "sections" entry."""
    idx = [i for i, n in enumerate(names) if n in SECTION_EVENTS]
    if len(idx) != len(IDS) or idx != list(range(idx[0], idx[0] + len(idx))):
        return list(names)
    return names[:idx[0]] + ["sections"] + names[idx[-1] + 1:]
