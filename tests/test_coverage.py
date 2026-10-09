from scripts.coverage import ROOT, coverage


def test_citations_resolve_and_d01_detected(monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("LLM_MODE", "replay")
    monkeypatch.delenv("LLM_RECORD_DIR", raising=False)
    r = coverage()
    assert r["cited"] and r["resolved"] == r["cited"]
    assert r["detected"] == ["D01"]
