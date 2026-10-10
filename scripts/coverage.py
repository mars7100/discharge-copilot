"""Compare the model's draft for case_001 against case_001_expected.json. Run: .venv/bin/python -m scripts.coverage"""
import json
import os
import uuid
from pathlib import Path

from langgraph.types import Command

from core.ingest import ingest_dir
from core.load_graph import load_graph
from core.validate import locate_quote

ROOT = Path(__file__).parent.parent
CLARIFICATION = "Medication A 5 mg initially, 10 mg from Day 3"  # same as the live fixture: this dev tool resolves, the app never does


def quote_spans(evidence, spans) -> set[str]:
    """Span IDs containing any of the evidence quotes (document_id + quote)."""
    return {s.span_id for e in evidence for s in spans.values()
            if s.document_id == e["document_id"] and locate_quote(e["quote"], s.text) is not None}


def coverage(spans=None, draft=None) -> dict:
    """Pass spans + draft to reuse a model run; otherwise runs the load graph."""
    expected = json.loads((ROOT / "fixtures" / "case_001_expected.json").read_text())
    if draft is None:
        docs, spans, _ = ingest_dir(ROOT / "fixtures" / "case_001")
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        out = load_graph.invoke({"documents": docs, "spans": spans}, config)
        if "__interrupt__" in out:
            answers = [{"conflict_id": c.conflict_id, "chosen_span_id": None, "clarification": CLARIFICATION}
                       for c in out["__interrupt__"][0].value]
            out = load_graph.invoke(Command(resume=answers), config)
        draft = out["draft"]
    cited = {sid for c in draft.claims for sid in c.evidence_span_ids}
    facts = expected["expected_facts"]
    missing = [f["fact_id"] for f in facts if not quote_spans(f["evidence"], spans) & cited]
    found = []
    for d in expected["discrepancies"]:
        # each side matches its evidence quote or a context quote from the same note
        want = [quote_spans([e] + [c for c in d.get("context_evidence", []) if c["document_id"] == e["document_id"]], spans)
                for e in d["evidence"]]
        if any(all(w & set(x.source_span_ids) for w in want) for x in draft.discrepancies):
            found.append(d["discrepancy_id"])
    return {"facts": len(facts), "missing": missing,
            "cited": len(cited), "resolved": len(cited & spans.keys()),
            "discrepancies": len(expected["discrepancies"]), "detected": found,
            "needs_review": [c.claim_id for c in draft.claims if c.support_status == "needs_review"]}


if __name__ == "__main__":
    os.chdir(ROOT)
    r = coverage()
    print(f"Known-fact coverage: {r['facts'] - len(r['missing'])}/{r['facts']}  missing: {', '.join(r['missing']) or '-'}")
    print(f"Citation resolution: {r['resolved']}/{r['cited']} cited span IDs exist")
    print(f"Discrepancies detected: {len(r['detected'])}/{r['discrepancies']}  {', '.join(r['detected'])}")
    print(f"Claims marked needs_review: {', '.join(r['needs_review']) or 'none'}")
