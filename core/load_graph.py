"""Load pipeline as a LangGraph graph: [extract_note x N, conflict_check] -> merge -> normalize -> resolve -> [draft_section x N] -> draft (join, dedupe) -> [retry_note per failed note] -> redraft_plan -> [draft_section x affected] -> draft (spec: Load graph)."""
import operator
import time
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

import core.extract
import core.models
import core.problems
import core.summarize
from core.conflicts import find_conflicts
from core.models import ClinicalEvent, ConflictItem, Discrepancy, Document, Draft, Resolution, SourceSpan, SummaryClaim

HC = "hospital_course"
RETRY_ATTEMPTS = 2  # per failed note, after the first draft
RETRY_DELAY = 2  # seconds before each attempt


class LoadState(TypedDict, total=False):
    documents: list[Document]
    spans: dict[str, SourceSpan]
    notes: Annotated[list[dict], operator.add]  # one record per note, in completion order
    conflicts: list[ConflictItem]
    conflict_warnings: list[str]
    events: list[ClinicalEvent]
    extract_warnings: list[str]
    problems: list[str]  # canonical problems in order, Other last
    conflict_problem: dict[str, str]
    discrepancies: list[Discrepancy]
    resolutions: list[Resolution]
    sections: Annotated[list[dict], operator.add]  # one record per template section, in completion order
    draft: Draft
    removed: list[SummaryClaim]
    draft_warnings: list[str]
    retried: bool  # set by the first draft: retries run once per load
    to_retry: list[str]
    retries: Annotated[list[dict], operator.add]  # one record per retried note, in completion order
    missing_notes: list[str]
    affected: list[list]  # [section_id, problem] groups the redraft covers


def fan_out(state: LoadState) -> list:
    return [Send("extract_note", note_input(state, d)) for d in state["documents"]] + ["conflict_check"]


def note_input(state: LoadState, d: Document) -> dict:
    return {"document": d, "spans": {k: s for k, s in state["spans"].items() if s.document_id == d.document_id}}


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
    conflicts = [c.model_copy(update={"conflict_id": d.discrepancy_id}) for c, d in zip(conflicts, discrepancies)]  # IDs follow the final order
    return {"events": events, "conflicts": conflicts, "extract_warnings": warnings + state["conflict_warnings"], "discrepancies": discrepancies}


def normalize(state: LoadState) -> dict:
    events, problems, conflict_problem, warnings = core.problems.normalize(state["events"], state["conflicts"])
    return {"events": events, "problems": problems, "conflict_problem": conflict_problem,
            "extract_warnings": state["extract_warnings"] + warnings}


def resolve(state: LoadState) -> dict:
    """Pauses on conflicts; resumes with [{conflict_id, chosen_span_id | None, clarification | None}], one per conflict (the API validates)."""
    if not state["conflicts"]:
        return {"resolutions": []}
    answers = {a["conflict_id"]: a for a in interrupt(state["conflicts"])}
    resolutions = []
    for c in state["conflicts"]:
        a = answers[c.conflict_id]
        text = (f"{c.description}: {next(q.quote for q in c.quotes if q.span_id == a['chosen_span_id'])}"
                if a["chosen_span_id"] else a["clarification"].strip())
        resolutions.append(Resolution(conflict_id=c.conflict_id, text=text, chosen_span_id=a["chosen_span_id"], quotes=c.quotes))
    return {"resolutions": resolutions,
            "discrepancies": [d.model_copy(update={"status": "clarified_pending_approval"}) for d in state["discrepancies"]]}


def overlaps(e: ClinicalEvent, conflicts: list[ConflictItem]) -> bool:
    """True when any evidence quote overlaps a conflict quote in the same span."""
    return any(r.span_id == q.span_id and r.start < q.start + len(q.quote) and q.start < r.start + len(r.quote)
               for r in e.evidence for c in conflicts for q in c.quotes)


def fan_out_sections(state: LoadState, only: list[list] | None = None) -> list:
    """only: the [section_id, problem] groups to draft (None: all)."""
    events = [e for e in state["events"] if not overlaps(e, state["conflicts"])]  # drafting never sees raw conflicting events
    common = {"spans": state["spans"], "problem": None}
    sends = [Send("draft_section", {**common, "section_id": t["section_id"], "events": events, "resolutions": state["resolutions"]})
             for t in core.models.TEMPLATE if t["section_id"] != HC and (only is None or [t["section_id"], None] in only)]
    for p in state["problems"]:  # one hospital_course call per problem that has events or resolutions
        evs = [e for e in events if e.problem == p]
        res = [r for r in state["resolutions"] if state["conflict_problem"][r.conflict_id] == p]
        if (evs or res) and (only is None or [HC, p] in only):
            sends.append(Send("draft_section", {**common, "section_id": HC, "problem": p, "events": evs, "resolutions": res}))
    return sends


def draft_section(state: dict) -> dict:
    rec = core.summarize.draft_section(state["section_id"], state["events"], state["spans"], state["resolutions"], state["problem"])
    return {"sections": [{"section_id": state["section_id"], "problem": state["problem"], **rec}]}


def draft(state: LoadState) -> dict:
    """Join in template order (never completion order), then dedupe."""
    d, warnings = core.summarize.assemble(state["sections"], state["resolutions"], state["problems"], state["conflict_problem"])
    d, removed, dedupe_warnings = core.summarize.dedupe(d.model_copy(update={"discrepancies": state["discrepancies"]}))
    failed = {n["document_id"] for n in state["notes"] if "detail" in n}
    return {"draft": d, "removed": removed, "retried": True, "to_retry": [] if state.get("retried") else [x.document_id for x in state["documents"] if x.document_id in failed],
            "draft_warnings": warnings + dedupe_warnings + [missing(x) for x in state.get("missing_notes", [])]}


def missing(document_id: str) -> str:
    return f"{document_id}: extraction failed after retries — the draft is missing this note"


def fan_out_retry(state: LoadState) -> list:
    return [Send("retry_note", note_input(state, d)) for d in state["documents"] if d.document_id in state["to_retry"]] or END


def retry_note(state: dict) -> dict:
    doc, detail = state["document"], "no attempt"
    for _ in range(RETRY_ATTEMPTS):
        time.sleep(RETRY_DELAY)
        try:
            events, warnings = core.extract.extract_events([doc], state["spans"])
        except Exception as e:
            detail = f"{type(e).__name__}: {e}"
        else:
            return {"retries": [{"document_id": doc.document_id, "events": events, "warnings": warnings}]}
    return {"retries": [{"document_id": doc.document_id, "detail": detail}]}


def redraft_plan(state: LoadState) -> dict:
    """Merges the recovered notes' events (new labels join the existing problems), then picks the groups whose input changed."""
    pos = {d.document_id: i for i, d in enumerate(state["documents"])}
    spans = state["spans"]
    retries = sorted(state["retries"], key=lambda r: pos[r["document_id"]])
    new = [e for r in retries for e in r.get("events", [])]
    new, _, _, warnings = core.problems.normalize(new, [], [p for p in state["problems"] if p != core.problems.OTHER])
    events = sorted(state["events"] + new, key=lambda e: (pos[spans[e.evidence[0].span_id].document_id], min(spans[r.span_id].order for r in e.evidence)))
    events = [e.model_copy(update={"event_id": f"E{i:02d}"}) for i, e in enumerate(events, 1)]  # same order as merge: document, then passage
    fresh = [e for e in new if not overlaps(e, state["conflicts"])]
    miss = [r["document_id"] for r in retries if "detail" in r]
    out = {"events": events, "problems": core.problems.problem_order(events, state["conflict_problem"]), "missing_notes": miss,
           "extract_warnings": state["extract_warnings"] + [w for r in retries for w in r.get("warnings", [])] + warnings,
           "affected": [[t["section_id"], None] for t in core.models.TEMPLATE if t["section_id"] != HC] * bool(fresh)
                       + [[HC, p] for p in dict.fromkeys(e.problem for e in fresh)]}
    if not fresh and miss:  # nothing to redraft: the same draft, with the missing-note warnings
        out |= {"draft": state["draft"], "draft_warnings": state["draft_warnings"] + [missing(d) for d in miss]}
    return out


def fan_out_redraft(state: LoadState) -> list:
    return fan_out_sections(state, state["affected"]) or END


def build():
    g = StateGraph(LoadState)
    g.add_node("extract_note", extract_note)
    g.add_node("conflict_check", conflict_check)
    g.add_node("merge", merge)
    g.add_node("normalize", normalize)
    g.add_node("resolve", resolve)
    g.add_node("draft_section", draft_section)
    g.add_node("draft", draft)
    g.add_node("retry_note", retry_note)
    g.add_node("redraft_plan", redraft_plan)
    g.add_conditional_edges(START, fan_out, ["extract_note", "conflict_check"])
    g.add_edge(["extract_note", "conflict_check"], "merge")
    g.add_edge("merge", "normalize")
    g.add_edge("normalize", "resolve")
    g.add_conditional_edges("resolve", fan_out_sections, ["draft_section"])
    g.add_edge("draft_section", "draft")
    g.add_conditional_edges("draft", fan_out_retry, ["retry_note", END])
    g.add_edge("retry_note", "redraft_plan")
    g.add_conditional_edges("redraft_plan", fan_out_redraft, ["draft_section", END])
    types = [("core.models", n) for n in vars(core.models) if getattr(getattr(core.models, n), "__module__", None) == "core.models"]  # state types restored from memory
    # ponytail: in-process memory, lost on restart
    return g.compile(checkpointer=InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=types))).with_config(max_concurrency=6)


load_graph = build()
