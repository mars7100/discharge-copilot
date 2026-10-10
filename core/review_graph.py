"""Typed review questions via a small LangGraph graph (spec §8): classify -> retrieve -> answer, or read section."""
import operator
import re
import uuid
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from core import llm
from core.export import SECTIONS, marker
from core.models import Draft, SourceSpan

NOT_ESTABLISHED = "The available notes do not establish that."
SYSTEM = f"""You answer a clinician's question about a synthetic hospitalization using ONLY the supplied note passages.
- Distinguish what the notes state; never add rationale, explanation or medical knowledge the passages do not state.
- If the passages do not answer the question, or part of it, say so with exactly this sentence, once: "{NOT_ESTABLISHED}" Do not also say it in other words.
- If passages give different values for the same item, state each value with its note date and cite every such passage; do not describe a change, order or resolution the passages do not state.
- "Flagged for review" lines come from this review tool, not from the notes: attribute any flagged conflict to the review tool, never say the notes flag it.
- span_ids: the IDs of the passages your answer relies on, copied exactly. Do not write span IDs in the answer text. Two to four sentences."""
HISTORY_TURNS = 3
HISTORY_NOTE = """Earlier turns of this conversation follow. Use them only to understand what the new question refers to.
Earlier answers are not evidence: rely on and cite only the passages supplied with the new question."""


class Answer(BaseModel):
    answer: str
    span_ids: list[str]


class State(TypedDict, total=False):
    question: str
    draft: Draft
    spans: dict[str, SourceSpan]
    events: list
    intent: str
    retrieved: list[str]
    answer: str
    cited: list[str]
    turns: Annotated[list[dict], operator.add]  # conversation so far, kept by the checkpointer


def classify(s: State) -> State:
    q = s["question"].lower()
    if q.startswith(("read", "show")) and any(t.lower() in q for t in SECTIONS.values()):
        return {"intent": "read_section"}
    return {"intent": "question" if len(q.split()) >= 2 else "unknown"}


def retrieve(s: State) -> State:
    markers = {marker(sp): sid for sid, sp in s["spans"].items()}
    direct = [markers[m] for m in re.findall(r"\[N\d\d:B\d\d\]", s["question"]) if m in markers]
    # ponytail: every passage goes to the model (6 short notes); lightweight RAG when cases get bigger
    return {"retrieved": direct or list(s["spans"])}


def note_date(spans: dict[str, SourceSpan], doc_id: str) -> str:
    """DATE line from the note's header span, e.g. '2026-03-04 (Hospital Day 3)'."""
    header = next((sp.text for sp in spans.values() if sp.document_id == doc_id and sp.order == 1), "")
    m = re.search(r"^DATE:[ \t]*(.+)$", header, re.M)
    return m.group(1) if m else "unknown"


def answer(s: State) -> State:
    if not s["retrieved"]:
        return {"answer": NOT_ESTABLISHED, "cited": []}
    passages = "\n".join(f"[{sid}] (note dated {note_date(s['spans'], s['spans'][sid].document_id)}) {s['spans'][sid].text}"
                         for sid in s["retrieved"])
    flags = "".join(f"\nFlagged for review by this app (not stated in the notes): {d.description}"
                    for d in s["draft"].discrepancies
                    if set(d.source_span_ids) & set(s["retrieved"]))
    history = [m for t in s.get("turns", [])[-HISTORY_TURNS:]
               for m in ({"role": "user", "content": t["q"]}, {"role": "assistant", "content": t["a"]})]
    messages = [{"role": "system", "content": SYSTEM},
                *([{"role": "system", "content": HISTORY_NOTE}] + history if history else []),
                {"role": "user", "content": f"Passages:\n{passages}{flags}\n\nQuestion: {s['question']}"}]
    out = llm.parse(Answer, messages)
    return {"answer": out.answer, "cited": [sid for sid in out.span_ids if sid in s["retrieved"]],  # drop unretrieved IDs
            "turns": [{"q": s["question"], "a": out.answer}]}


def read_section(s: State) -> State:
    q = s["question"].lower()
    key = next(k for k, t in SECTIONS.items() if t.lower() in q)
    claims = [c for c in s["draft"].claims if c.section == key]
    text = " ".join(c.text for c in claims) or "Not documented in the supplied notes."
    return {"answer": text, "cited": [sid for c in claims for sid in c.evidence_span_ids],
            "turns": [{"q": s["question"], "a": text}]}


def clarify(s: State) -> State:
    return {"answer": "Please ask a question about the notes or the draft.", "cited": []}


g = StateGraph(State)
for name, fn in [("classify", classify), ("retrieve", retrieve), ("answer", answer),
                 ("read_section", read_section), ("clarify", clarify)]:
    g.add_node(name, fn)
g.add_edge(START, "classify")
g.add_conditional_edges("classify", lambda s: s["intent"],
                        {"question": "retrieve", "read_section": "read_section", "unknown": "clarify"})
g.add_edge("retrieve", "answer")
for n in ("answer", "read_section", "clarify"):
    g.add_edge(n, END)
CHECKPOINT_TYPES = [("core.models", c) for c in ("Draft", "SourceSpan", "ClinicalEvent")]  # state types restored from memory
graph = g.compile(checkpointer=InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)))  # ponytail: in-process memory, lost on restart


def ask(question: str, draft: Draft, spans: dict[str, SourceSpan], events=(), thread_id: str | None = None) -> State:
    """Same thread_id = same conversation; None starts a fresh one."""
    return graph.invoke({"question": question, "draft": draft, "spans": spans, "events": list(events)},
                        {"configurable": {"thread_id": thread_id or uuid.uuid4().hex}})
