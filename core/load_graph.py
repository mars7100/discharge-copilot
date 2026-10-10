"""Load pipeline as a two-node LangGraph graph: extract -> draft (spec: Load graph)."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import core.extract
import core.summarize
from core.models import ClinicalEvent, Document, Draft, SourceSpan


class LoadState(TypedDict, total=False):
    documents: list[Document]
    spans: dict[str, SourceSpan]
    events: list[ClinicalEvent]
    extract_warnings: list[str]
    draft: Draft
    draft_warnings: list[str]


def extract(state: LoadState) -> dict:
    events, warnings = core.extract.extract_events(state["documents"], state["spans"])
    return {"events": events, "extract_warnings": warnings}


def draft(state: LoadState) -> dict:
    d, warnings = core.summarize.generate_draft(state["events"], state["spans"])
    return {"draft": d, "draft_warnings": warnings}


def build():
    g = StateGraph(LoadState)
    g.add_node("extract", extract)
    g.add_node("draft", draft)
    g.add_edge(START, "extract")
    g.add_edge("extract", "draft")
    g.add_edge("draft", END)
    return g.compile()


load_graph = build()
