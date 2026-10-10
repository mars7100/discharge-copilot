import pytest

from scripts.coverage import coverage

pytestmark = pytest.mark.live  # uses the model; run with: pytest -m live


def test_citations_resolve_and_d01_detected(case_copy):
    r = coverage(case_copy.spans, case_copy.draft)
    assert r["cited"] and r["resolved"] == r["cited"]
    assert r["detected"] == ["D01"]
