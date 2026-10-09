import json
import re
from pathlib import Path

import pymupdf

from core.ingest import ingest, ingest_dir

FIX = Path(__file__).parent.parent / "fixtures"
norm = lambda s: re.sub(r"\s+", " ", s).strip()


def test_fixture_ids_stable_and_headers_parsed():
    docs, spans, warnings = ingest_dir(FIX / "case_001")
    assert warnings == []
    assert [d.document_id for d in docs] == [f"note_0{i}" for i in range(1, 7)]
    assert (docs[3].date, docs[3].hospital_day) == ("2026-03-04", 3)
    assert docs[4].type == "Day shift nursing note"
    assert list(ingest_dir(FIX / "case_001")[1]) == list(spans)  # same input, same IDs
    assert "note_01_p01_b01" in spans and "NOTE_ID: note_01" in spans["note_01_p01_b01"].text


def test_every_expected_quote_is_inside_one_span():
    _, spans, _ = ingest_dir(FIX / "case_001")
    exp = json.loads((FIX / "case_001_expected.json").read_text())
    refs = [e for f in exp["expected_facts"] for e in f["evidence"]]
    refs += [e for d in exp["discrepancies"] for e in d["evidence"]]
    for r in refs:
        assert any(norm(r["quote"]) in norm(s.text) for s in spans.values()
                   if s.document_id == r["document_id"]), r


def test_pdf_pages_and_bad_inputs():
    pdf = pymupdf.open()
    for text in ("Page one block.\n\nSecond block.", "Page two block."):
        pdf.new_page().insert_text((72, 72), text)
    blank = pymupdf.open()
    blank.new_page()
    docs, spans, warnings = ingest([("../x/scan.pdf", pdf.tobytes()), ("empty.pdf", blank.tobytes()),
                                    ("img.png", b""), ("broken.pdf", b"not a pdf")])
    assert [d.document_id for d in docs] == ["scan"]
    assert {s.page for s in spans.values()} == {1, 2}
    assert len(warnings) == 3
