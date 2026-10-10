import pytest

from scripts.coverage import coverage

pytestmark = pytest.mark.live  # uses the model; run with: pytest -m live -s


def test_citations_resolve_and_d01_detected(case_copy):
    r = coverage(case_copy.spans, case_copy.draft)
    print(f"\ncase_001 load wall time (load graph): {case_copy.load_seconds:.1f} s (baseline 41–55 s)")
    assert r["cited"] and r["resolved"] == r["cited"]
    assert r["detected"] == ["D01"]
