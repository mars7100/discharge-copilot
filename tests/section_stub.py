"""Shared stub helpers for ticket 08 (per-section drafting), used by the core.llm.parse stubs of tickets 03a/06/07/08.

Test-imposed assumptions (the 08 contract leaves the schema name and prompt wording open):
- A section drafting call's structured-output schema has a `documented` field (and a `claims` list whose items accept
  the SummaryClaim fields section, text, evidence_span_ids, clinician_clarification_ids).
- The messages of a section call, before any assistant turn, name exactly one template section_id: the section drafted.

Ticket 09 additions (test-imposed; the 09 contract leaves the schema name and prompt wording open):
- The problem-normalization schema is recognized structurally: a top-level list field whose item model has exactly one
  `str` field (the canonical problem name) and two list fields; the list field whose name contains "conflict" holds
  conflict IDs (D01...), the other holds raw problem labels. Stub outputs are built with model_construct, so unknown
  labels/IDs reach the code even if the implementation narrows the item types.
- A hospital_course call names its canonical problem in a line "Problem: <name>" before any assistant turn.
"""
import re
from typing import get_origin

from pydantic import BaseModel

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
    if problem_list(schema):
        return "normalize"
    raise AssertionError(f"unexpected schema {schema.__name__}: ticket 08 drafts each section with a schema that has "
                         "a `documented` field; ticket 09 normalizes problems with a list of {name, labels, conflict IDs}")


def problem_list(schema):
    """(field name, item model) of a normalization schema's problem list, else None."""
    for name, f in schema.model_fields.items():
        args = getattr(f.annotation, "__args__", ())
        item = args[0] if get_origin(f.annotation) is list and args else None
        if isinstance(item, type) and issubclass(item, BaseModel):
            types = [g.annotation for g in item.model_fields.values()]
            if types.count(str) == 1 and sum(get_origin(t) is list for t in types) == 2:
                return name, item
    return None


def normalization(schema, problems=()):
    """problems: [(canonical name, [raw labels], [conflict IDs])], in the model's order."""
    field, item = problem_list(schema)
    fields = item.model_fields
    name = next(n for n, f in fields.items() if f.annotation is str)
    ids = next(n for n, f in fields.items() if get_origin(f.annotation) is list and "conflict" in n.lower())
    labels = next(n for n, f in fields.items() if get_origin(f.annotation) is list and n != ids)
    return schema.model_construct(**{field: [item.model_construct(**{name: p, labels: list(l), ids: list(c)})
                                             for p, l, c in problems]})


def problem_of(messages) -> str:
    initial = []
    for m in messages:
        if m["role"] == "assistant":
            break
        initial.append(str(m["content"]))
    found = set(re.findall(r"^Problem: (.+?)\s*$", "\n".join(initial), re.M))
    assert len(found) == 1, f"a hospital_course call must name its problem in one 'Problem: <name>' line, found {found}"
    return found.pop()


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
