"""Live tests share one model run of case_001 (extraction + summary) per pytest session."""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.extract
import core.summarize
from core.ingest import ingest_dir

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def case001():
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(ROOT)
        docs, spans, _ = ingest_dir(ROOT / "fixtures" / "case_001")
        events, extract_warnings = core.extract.extract_events(docs, spans)
        draft, summary_warnings = core.summarize.generate_draft(events, spans)
    return SimpleNamespace(docs=docs, spans=spans, events=events, extract_warnings=extract_warnings,
                           draft=draft, summary_warnings=summary_warnings)


@pytest.fixture
def case_copy(case001):
    """A fresh copy per test, so no test sees another test's changes."""
    return copy.deepcopy(case001)


@pytest.fixture(autouse=True)
def reuse_case_in_app(request, monkeypatch):
    """Live tests: the app's 'Load sample case' reuses the session's model run instead of calling the model again."""
    if not request.node.get_closest_marker("live"):
        return  # non-live tests never load the case
    c = copy.deepcopy(request.getfixturevalue("case001"))
    monkeypatch.setattr(core.extract, "extract_events", lambda docs, spans: (c.events, c.extract_warnings))
    monkeypatch.setattr(core.summarize, "generate_draft", lambda events, spans: (c.draft, c.summary_warnings))
