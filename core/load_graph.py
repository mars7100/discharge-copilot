"""Load pipeline as a LangGraph graph: [extract_note x N, conflict_check] -> merge -> draft (spec: Load graph)."""
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

import core.extract
import core.summarize
from core.conflicts import find_conflicts
from core.models import ClinicalEvent, ConflictItem, Discrepancy, Document, Draft, SourceSpan


class LoadState(TypedDict, total=False):
    documents: list[Document]
    spans: dict[str, SourceSpan]
    notes: Annotated[list[dict], operator.add]  # one record per note, in completion order
    conflicts: list[ConflictItem]
    conflict_warnings: list[str]
    events: list[ClinicalEvent]
    extract_warnings: list[str]
    discrepancies: list[Discrepancy]
    draft: Draft
    draft_warnings: list[str]


def fan_out(state: LoadState) -> list:
    return [Send("extract_note", {"document": d, "spans": {k: s for k, s in state["spans"].items() if s.document_id == d.document_id}})
            for d in state["documents"]] + ["conflict_check"]


def extract_note(state: dict) -> dict:
    doc = state["document"]
    try:
        events, warnings = core.extract.extract_events([doc], state["spans"])
    except Exception as e:  # a failed note never fails the load
        return {"notes": [{"document_id": doc.document_id, "detail": f"{type(e).__name__}: {e}"}]}
    return {"notes": [{"document_id": doc.document_id, "events": events, "warnings": warnings}]}


def conflict_check(state: LoadState) -> dict:
    conflicts, warnings = find_conflicts(state["documents"], state["spans"])
    return {"conflicts": conflicts, "conflict_warnings": warnings}


def merge(state: LoadState) -> dict:
    """Deterministic: ordering depends on model output and document order, never on completion order."""
    pos = {d.document_id: i for i, d in enumerate(state["documents"])}
    spans = state["spans"]
    notes = sorted(state["notes"], key=lambda n: pos[n["document_id"]])
    if all("detail" in n for n in notes):
        raise core.extract.ExtractionError("all notes failed: " + "; ".join(f"{n['document_id']}: {n['detail']}" for n in notes))
    keyed = [((pos[n["document_id"]], min(spans[r.span_id].order for r in e.evidence), i), e)
             for n in notes for i, e in enumerate(n.get("events", []))]
    events = [e.model_copy(update={"event_id": f"E{i:02d}"}) for i, (_, e) in enumerate(sorted(keyed, key=lambda k: k[0]), 1)]
    warnings = [w for n in notes for w in ([f"{n['document_id']}: failed — {n['detail']}"] if "detail" in n else n["warnings"])]

    def first(c):
        s = spans[c.quotes[0].span_id]
        return pos[s.document_id], s.order
    conflicts = sorted(state["conflicts"], key=first)
    discrepancies = [Discrepancy(discrepancy_id=f"D{i:02d}", description=c.description,
                                 source_span_ids=[q.span_id for q in c.quotes]) for i, c in enumerate(conflicts, 1)]
    return {"events": events, "extract_warnings": warnings + state["conflict_warnings"], "discrepancies": discrepancies}


def draft(state: LoadState) -> dict:
    d, warnings = core.summarize.generate_draft(state["events"], state["spans"])
    return {"draft": d.model_copy(update={"discrepancies": state["discrepancies"]}), "draft_warnings": warnings}


def build():
    g = StateGraph(LoadState)
    g.add_node("extract_note", extract_note)
    g.add_node("conflict_check", conflict_check)
    g.add_node("merge", merge)
    g.add_node("draft", draft)
    g.add_conditional_edges(START, fan_out, ["extract_note", "conflict_check"])
    g.add_edge(["extract_note", "conflict_check"], "merge")
    g.add_edge("merge", "draft")
    g.add_edge("draft", END)
    return g.compile().with_config(max_concurrency=6)


load_graph = build()
