import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core.export import to_markdown
from core.models import SummaryClaim
from core.summarize import check_claims

pytestmark = pytest.mark.live  # uses the model; run with: pytest -m live

ROOT = Path(__file__).parent.parent


@pytest.fixture
def live_draft(case_copy):
    return case_copy.docs, case_copy.spans, case_copy.draft, case_copy.summary_warnings


def test_unknown_span_ids_dropped_and_reported(live_draft):  # T12
    _, spans, _, _ = live_draft
    c = SummaryClaim(claim_id="C01", section="follow_up", text="x",
                     evidence_span_ids=["note_06_p01_b09", "note_99_p01_b01"], support_status="unverified")
    bad = c.model_copy(update={"claim_id": "C02", "evidence_span_ids": ["nope"]})
    valid, errors = check_claims([c, bad], spans)
    assert [v.evidence_span_ids for v in valid] == [["note_06_p01_b09"]]
    assert any("note_99_p01_b01" in e for e in errors) and any("C02" in e for e in errors)


def test_case_001_draft_flags_only_the_medication_conflict(live_draft):
    _, spans, draft, warnings = live_draft
    assert not any("retry failed" in w for w in warnings), warnings
    assert all(s in spans for c in draft.claims for s in c.evidence_span_ids)  # T03
    assert [d.source_span_ids for d in draft.discrepancies] == [["note_04_p01_b07", "note_05_p01_b04"]]  # T04
    flagged = [c for c in draft.claims if c.support_status == "needs_review"]
    assert flagged and all("Medication A" in c.text for c in flagged)


def test_export_labels_and_appendix(live_draft):
    docs, spans, draft, _ = live_draft
    md = to_markdown(draft, spans, docs)
    assert "SYNTHETIC DEMONSTRATION — NOT FOR CLINICAL USE" in md and "DRAFT — NOT APPROVED" in md
    assert "## Source appendix" in md and spans["note_05_p01_b04"].text.splitlines()[0] in md
    approved = draft.model_copy(update={"status": "approved", "approved_at": __import__("datetime").datetime(2026, 10, 9),
                                        "reviewer": "Simulated resident"})
    assert "APPROVED by Simulated resident" in to_markdown(approved, spans, docs)


def test_app_load_cite_approve(monkeypatch):
    monkeypatch.chdir(ROOT)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    at.sidebar.button[0].click().run()  # Load sample case
    assert not at.exception and "Draft" in at.subheader[0].value
    passage = at.session_state["spans"]["note_05_p01_b04"].text.splitlines()[0]
    assert any(passage in m.value for m in at.markdown)  # exact passage rendered (popover / needs-review)
    draft_before = at.session_state["draft"]
    at.text_area[0].set_value("Medication A: 5 mg initially, 10 mg from Hospital Day 3 (clinician-provided).")
    next(b for b in at.button if b.label == "Propose correction").click().run()
    assert at.session_state["draft"] == draft_before  # T06: unchanged before accept
    next(b for b in at.button if b.label == "Accept").click().run()
    assert at.session_state["draft"] != draft_before and not at.exception
    next(b for b in at.button if b.label == "Approve draft").click().run()
    assert "Approved" in at.subheader[0].value
