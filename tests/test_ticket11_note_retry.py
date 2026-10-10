"""Specification tests for ticket 11 (failed-note background retry), see issues/11-contract.md.

Seams: the HTTP API through TestClient (load + resolutions SSE, session state, editing endpoints, export), which drives
core.load_graph.load_graph. The model is stubbed only at core.llm.parse: a chosen note's extraction calls raise a chosen
number of times (each core.extract.extract_events attempt makes two parse calls when the first raises). Section calls echo
the statements of the events in their prompt as claims (claim text = statement), so a snapshot shows which events reached
which section. core.load_graph.RETRY_ATTEMPTS / RETRY_DELAY are monkeypatched (contract names).

Test-imposed interfaces:
- The retry delay is a call to `time.sleep(RETRY_DELAY)` (through the `time` module, or a module-level `sleep` name in
  core.load_graph), so a recorder can count it.
- The retry normalization call is recognized by its schema (as in 09, tests/section_stub.py). The existing canonical
  problems are passed to it as lines `Problem: <name>` (one per existing problem other than Other); the new raw labels
  appear in its messages.
"""
import collections
import re
import threading
import time

import pytest

import core.load_graph
from core import llm
from core.extract import ExtractionResult
from core.models import ClinicalEvent
from tests.section_stub import EVERY_SECTION, IDS, SECTION_EVENTS, dedupe_result, kind, normalization, problem_of, section_of, section_result
from tests.test_api import client, create, state  # noqa: F401  (client is a fixture)
from tests.test_api_ticket04 import OPERATIONS, approve, call
from tests.test_ticket06_parallel_load import conflict_result
from tests.test_ticket07_resolve_conflicts import CLARIFICATION, DESC, Q04, Q05, SPANS, clarify, load, plain_span, submit, text_of

HC = "hospital_course"
NON_HC = [s for s in IDS if s != HC]
ECHO = {HC, "key_events"}  # sections whose stub output echoes their events; the others answer documented=false
DELAY = 0.001234           # sentinel RETRY_DELAY: sleeps of this length are recorded, not slept
WAIT = 2
NOTES = ["note_01", "note_02", "note_03", "note_04", "note_05", "note_06"]


def ev(doc, k, label, ref=None):
    s = plain_span(doc)
    span, quote = ref or (s.span_id, s.text)
    return ClinicalEvent(event_id="x", date_or_hospital_day="Hospital Day 2", category="other", statement=f"{doc} fact {k}",
                         problem=label, evidence=[{"span_id": span, "quote": quote}],
                         sections=EVERY_SECTION)  # ticket 12: routed to every section, as before


def events():
    """Per-note extraction output. Every event cites its note's first plain passage, so merged order is note order then
    model index."""
    return {"note_01": [ev("note_01", 1, "CAP")],
            "note_02": [ev("note_02", 1, "AKI"), ev("note_02", 2, "HTN"), ev("note_02", 3, None)],
            "note_03": [ev("note_03", 1, "HTN")],
            "note_04": [ev("note_04", 1, "community-acquired pneumonia")],
            "note_05": [ev("note_05", 1, "HTN")],
            "note_06": [ev("note_06", 1, None)]}


FIRST = [("Pneumonia", ["CAP", "community-acquired pneumonia"], []), ("Hypertension", ["HTN"], []),
         ("Acute kidney injury", ["AKI"], [])]


class Model:
    """Stub for core.llm.parse.
    fails: document_id -> number of that note's extraction calls that raise (the rest succeed); float("inf") = always.
    normalize: answers per normalization call (last repeats); "raise" raises.
    timeline: ("extract", doc) / ("sleep", None) in call order. summary: (section, problem, messages) per section call."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events = events()
        self.fails = {}
        self.conflicts = []
        self.normalize = [FIRST]
        self.normalize_calls, self.dedupe, self.summary, self.timeline = [], [], [], []
        self.raising = set()
        self.on_extract = lambda doc, n: None

    def statements(self):
        return [e.statement for d in NOTES for e in self.events[d]]

    def extracts(self, doc):
        return [x for x in self.timeline if x == ("extract", doc)]

    def __call__(self, schema, messages, timeout):
        k = kind(schema)
        if k == "extract":
            doc = next(d for d in NOTES if plain_span(d).span_id in text_of(messages))
            with self.lock:
                self.timeline.append(("extract", doc))
                n = len(self.extracts(doc))
            self.on_extract(doc, n)
            if n <= self.fails.get(doc, 0):
                raise RuntimeError(f"{doc} extraction boom")
            return ExtractionResult(events=self.events[doc])
        if k == "conflict":
            return conflict_result(schema, self.conflicts)
        if k == "normalize":
            with self.lock:
                self.normalize_calls.append([dict(m) for m in messages])
                answer = self.normalize[min(len(self.normalize_calls), len(self.normalize)) - 1]
            if answer == "raise":
                raise RuntimeError("normalization boom")
            return normalization(schema, answer)
        if k == "dedupe":
            with self.lock:
                self.dedupe.append(messages)
            return dedupe_result(schema)
        sec = section_of(messages)
        problem = problem_of(messages) if sec == HC else None
        with self.lock:
            self.summary.append((sec, problem, [dict(m) for m in messages]))
        if (sec, problem) in self.raising:
            raise RuntimeError(f"{sec}/{problem} boom")
        prompt = text_of(messages)
        spans = {e.statement: e.evidence[0].span_id for d in NOTES for e in self.events[d]}
        claims = [{"section": sec, "text": s, "evidence_span_ids": [spans[s]]} for s in self.statements()
                  if s in prompt] if sec in ECHO else []
        return section_result(schema, bool(claims), claims)

    def section_counts(self):
        return collections.Counter((s, p) for s, p, _ in self.summary)


@pytest.fixture
def model(monkeypatch):
    m = Model()
    monkeypatch.setattr(llm, "parse", m)
    monkeypatch.setattr(core.load_graph, "RETRY_ATTEMPTS", 2, raising=False)
    monkeypatch.setattr(core.load_graph, "RETRY_DELAY", DELAY, raising=False)
    real = time.sleep

    def sleep(seconds):
        if seconds == DELAY:
            with m.lock:
                m.timeline.append(("sleep", None))
        else:
            real(seconds)
    monkeypatch.setattr(time, "sleep", sleep)
    if hasattr(core.load_graph, "sleep"):
        monkeypatch.setattr(core.load_graph, "sleep", sleep)
    return m


def sleeps(model):
    return model.timeline.count(("sleep", None))


def run(client, model, sid=None):
    """Loads (and with conflicts, clarifies D01). Returns (sid, load SSE, resume SSE or [])."""
    sid = sid or create(client)
    sse, resumed = load(client, sid), []
    if model.conflicts:
        assert sse[-1][0] == "conflicts_found", sse
        status, resumed = submit(client, sid, [clarify()])
        assert status == 200
    return sid, sse, resumed


def after_first_draft(sse):
    names = [n for n, _ in sse]
    assert "draft" in names, names
    return sse[names.index("draft") + 1:]


def settled(sse):
    """The tail after the first draft: (note_retrying document_ids, settle events, rest)."""
    tail = after_first_draft(sse)
    names = [n for n, _ in tail]
    retrying = [d["document_id"] for n, d in tail if n == "note_retrying"]
    assert names[:len(retrying)] == ["note_retrying"] * len(retrying), names  # one per failed note, before any settle
    settles = tail[len(retrying):len(retrying) * 2]
    assert sorted(d["document_id"] for _, d in settles) == sorted(retrying), names
    assert all(n in ("note_extracted", "note_failed") for n, _ in settles), names
    return retrying, dict((d["document_id"], (n, d)) for n, d in settles), [n for n, _ in tail[len(retrying) * 2:]]


def drafts(sse):
    return [d for n, d in sse if n == "draft"]


def rows(draft):
    return [(c["section"], c["problem"], c["text"]) for c in draft["claims"]]


def export_lines(client, sid):
    assert approve(client, sid).status_code == 200
    r = client.get(f"/api/sessions/{sid}/export")
    assert r.status_code == 200
    return r.text.splitlines()


def incomplete_line(lines):
    """The first non-empty line after the status lines (they end with "- Generated: ...")."""
    i = next(i for i, ln in enumerate(lines) if ln.startswith("- Generated:"))
    return next(ln for ln in lines[i + 1:] if ln.strip())


def missing(doc):
    return f"{doc}: extraction failed after retries — the draft is missing this note"


# ---------- no failed notes ----------

def test_no_failed_notes_streams_and_calls_exactly_as_before(client, model):
    sid, sse, _ = run(client, model)
    names = [n for n, _ in sse]
    assert names[-3:] == ["dedupe_applied", "draft", "done"] and names.count("draft") == 1
    assert "note_retrying" not in names and "note_failed" not in names
    assert all(len(model.extracts(d)) == 1 for d in NOTES) and sleeps(model) == 0
    assert len(model.normalize_calls) == 1 and len(model.dedupe) == 1
    assert set(model.section_counts().values()) == {1}
    s = state(client, sid)
    assert s["missing_notes"] == [] and s["load_running"] is False
    assert not incomplete_line(export_lines(client, sid)).startswith("**Incomplete")


# ---------- successful retry ----------

def recovered(client, model, **normalize):
    """note_02 fails its first-pass extraction (both calls of its validation retry) and recovers on the first retry."""
    model.fails = {"note_02": 2}
    if normalize:
        model.normalize = [FIRST, normalize["retry"], normalize["retry"]]
    sid, sse, _ = run(client, model)
    assert sse[-1][0] == "done", sse
    return sid, sse


def test_successful_retry_redrafts_only_affected_groups_reruns_dedupe_and_streams_a_new_snapshot(client, model):
    sid, sse = recovered(client, model)

    first_pass = [n for n, _ in sse][:[n for n, _ in sse].index("draft") + 1]
    assert first_pass.count("note_failed") == 1 and "note_retrying" not in first_pass  # first pass unchanged
    retrying, settles, rest = settled(sse)
    assert retrying == ["note_02"]
    name, data = settles["note_02"]
    assert name == "note_extracted" and data == {"document_id": "note_02", "event_count": 3, "warnings": []}
    # affected groups: Acute kidney injury (new), Hypertension and Other (gained an event); Pneumonia is unaffected
    n_redrafted = len(NON_HC) + 3
    assert set(rest[:n_redrafted]) <= set(SECTION_EVENTS) and rest[n_redrafted:] == ["dedupe_applied", "draft", "done"]
    hc = sorted(d["problem"] for n, d in after_first_draft(sse) if n == "section_drafted" and d["section_id"] == HC)
    assert hc == ["Acute kidney injury", "Hypertension", "Other"]

    expected_calls = {**{(s, None): 2 for s in NON_HC}, (HC, "Pneumonia"): 1, (HC, "Hypertension"): 2, (HC, "Other"): 2,
                      (HC, "Acute kidney injury"): 1}
    assert dict(model.section_counts()) == expected_calls
    assert len(model.dedupe) == 2
    assert len(model.extracts("note_02")) == 3 and sleeps(model) == 1  # one retry attempt, after one delay

    first, last = drafts(sse)
    assert not [t for _, _, t in rows(first["draft"]) if t.startswith("note_02")]
    by_problem = [("Pneumonia", ["note_01 fact 1", "note_04 fact 1"]), ("Acute kidney injury", ["note_02 fact 1"]),
                  ("Hypertension", ["note_02 fact 2", "note_03 fact 1", "note_05 fact 1"]),
                  ("Other", ["note_02 fact 3", "note_06 fact 1"])]
    assert rows(last["draft"]) == ([(HC, p, t) for p, ts in by_problem for t in ts]
                                   + [("key_events", None, t) for t in model.statements()])
    assert [c["claim_id"] for c in last["draft"]["claims"]] == [f"C{i:02d}" for i in range(1, len(last["draft"]["claims"]) + 1)]
    s = state(client, sid)
    assert s["draft"] == last["draft"] and s["missing_notes"] == [] and s["load_running"] is False
    assert [(e["event_id"], e["statement"]) for e in s["events"]] == [
        (f"E{i:02d}", t) for i, t in enumerate(model.statements(), 1)]  # merged in note order, renumbered E01...
    assert not incomplete_line(export_lines(client, sid)).startswith("**Incomplete")


@pytest.mark.parametrize("normalization_ok", [True, False])
def test_new_events_join_existing_problems_create_new_ones_and_never_rename(client, model, normalization_ok):
    if normalization_ok:  # the model also tries to rename the existing Pneumonia problem: ignored
        retry = [("Hypertension", ["HTN"], []), ("Acute kidney injury", ["AKI"], []),
                 ("Lung infection", ["CAP", "community-acquired pneumonia", "Pneumonia"], [])]
        new_label, aki = "HTN", "Acute kidney injury"
    else:  # fallback: raw labels; one matches an existing problem case-insensitively and joins it
        retry, new_label, aki = "raise", "hypertension", "AKI"
    model.events["note_02"][1] = ev("note_02", 2, new_label)
    sid, sse = recovered(client, model, retry=retry)

    problems = {e["statement"]: e["problem"] for e in state(client, sid)["events"]}
    assert problems == {"note_01 fact 1": "Pneumonia", "note_02 fact 1": aki, "note_02 fact 2": "Hypertension",
                        "note_02 fact 3": "Other", "note_03 fact 1": "Hypertension", "note_04 fact 1": "Pneumonia",
                        "note_05 fact 1": "Hypertension", "note_06 fact 1": "Other"}
    groups = list(dict.fromkeys(c["problem"] for c in drafts(sse)[-1]["draft"]["claims"] if c["section"] == HC))
    assert groups == ["Pneumonia", aki, "Hypertension", "Other"]  # 09 order: first appearance in merged events
    assert (HC, "Lung infection") not in model.section_counts()

    retry_call = text_of(model.normalize_calls[1])  # the call after the first pass
    assert "AKI" in retry_call and new_label in retry_call
    for p in ("Pneumonia", "Hypertension"):  # existing canonical problems are passed in
        assert re.search(rf"^Problem: {p}\s*$", retry_call, re.M), retry_call


# ---------- final failure ----------

@pytest.mark.parametrize("failing, attempts", [(["note_03"], 1), (["note_03"], 2), (["note_03", "note_05"], 2)])
def test_final_failure_tells_the_resident_and_the_export_after_exactly_retry_attempts(client, model, monkeypatch,
                                                                                       failing, attempts):
    monkeypatch.setattr(core.load_graph, "RETRY_ATTEMPTS", attempts, raising=False)
    model.fails = {d: float("inf") for d in failing}
    sid, sse, _ = run(client, model)

    for d in failing:  # first pass: one attempt; then RETRY_ATTEMPTS attempts; two parse calls each
        assert len(model.extracts(d)) == 2 * (1 + attempts), d
    assert sleeps(model) == attempts * len(failing)
    if len(failing) == 1:  # each attempt is preceded by the delay
        assert [k for k, _ in model.timeline if k == "sleep" or _ == failing[0]] == (
            ["extract"] * 2 + (["sleep"] + ["extract"] * 2) * attempts)
    retrying, settles, rest = settled(sse)
    assert retrying == failing
    for d in failing:
        name, data = settles[d]
        assert name == "note_failed" and set(data) == {"document_id", "detail"} and data["detail"]
    assert rest == ["draft", "done"]  # nothing redrafted: a snapshot with the warning, then done
    first, last = drafts(sse)
    assert all(missing(d) in last["warnings"] for d in failing), last["warnings"]
    assert last["draft"]["claims"] == first["draft"]["claims"]
    assert set(model.section_counts().values()) == {1} and len(model.dedupe) == 1

    s = state(client, sid)
    assert s["missing_notes"] == failing and s["load_running"] is False and s["draft"] == last["draft"]
    assert incomplete_line(export_lines(client, sid)) == (
        f"**Incomplete: notes not included (extraction failed): {', '.join(failing)}**")


def test_missing_note_warning_is_in_the_redrafted_snapshot_when_another_note_recovers(client, model):
    model.fails = {"note_02": 2, "note_05": float("inf")}
    sid, sse, _ = run(client, model)

    retrying, settles, rest = settled(sse)  # both settle before any redraft
    assert retrying == ["note_02", "note_05"]
    assert settles["note_02"][0] == "note_extracted" and settles["note_05"][0] == "note_failed"
    assert rest[-3:] == ["dedupe_applied", "draft", "done"] and set(rest[:-3]) <= set(SECTION_EVENTS)
    last = drafts(sse)[-1]
    assert missing("note_05") in last["warnings"]
    assert "note_02 fact 1" in [t for _, _, t in rows(last["draft"])]
    assert len(model.dedupe) == 2
    assert state(client, sid)["missing_notes"] == ["note_05"]


# ---------- concurrency, one redraft ----------

def test_two_failed_notes_are_retried_concurrently_then_one_redraft_and_one_dedupe(client, model):
    model.fails = {"note_02": 2, "note_05": 2}
    cv, live = threading.Condition(), {"now": 0, "max": 0, "started": 0}

    def hold(doc, n):  # each retry attempt stays in flight until both have started (or WAIT passes)
        if n <= 2:
            return
        with cv:
            live["now"] += 1
            live["started"] += 1
            live["max"] = max(live["max"], live["now"])
            cv.notify_all()
            cv.wait_for(lambda: live["started"] == 2, timeout=WAIT)
            live["now"] -= 1
    model.on_extract = hold
    sid, sse, _ = run(client, model)

    assert live["max"] == 2, live
    retrying, settles, rest = settled(sse)
    assert retrying == ["note_02", "note_05"]
    assert {d: n for d, (n, _) in settles.items()} == {"note_02": "note_extracted", "note_05": "note_extracted"}
    assert rest[-3:] == ["dedupe_applied", "draft", "done"] and set(rest[:-3]) <= set(SECTION_EVENTS)
    assert len(drafts(sse)) == 2 and len(model.dedupe) == 2
    assert all(model.section_counts()[(s, None)] == 2 for s in NON_HC)  # one redraft for both notes
    texts = [t for _, _, t in rows(drafts(sse)[-1]["draft"])]
    assert "note_02 fact 1" in texts and "note_05 fact 1" in texts


# ---------- editing lock ----------

def test_editing_endpoints_return_409_after_the_first_draft_until_done(client, model):
    model.fails = {"note_02": 2}
    seen = {}

    def peek(doc, n):  # during the retry attempt, from another thread
        if (doc, n) != ("note_02", 3):
            return

        def probe():
            s = client.get(f"/api/sessions/{sid}").json()
            seen["state"] = (s["load_running"], s["draft"] is not None)
            seen["ops"] = {op: call(client, sid, op).status_code for op in OPERATIONS}
        t = threading.Thread(target=probe)
        t.start()
        t.join(WAIT)
    model.on_extract = peek
    sid = create(client)
    run(client, model, sid)

    assert "state" in seen, "note_02 was never retried"
    assert seen["state"] == (True, True)  # the first draft is in the session, the load still runs
    assert seen["ops"] == {op: 409 for op in OPERATIONS}
    assert state(client, sid)["load_running"] is False
    assert approve(client, sid).status_code == 200  # unlocked after done


# ---------- conflicts ----------

@pytest.mark.parametrize("overlapping_only", [True, False])
def test_with_conflicts_retries_run_after_the_resume_first_draft(client, model, overlapping_only):
    model.conflicts = [(DESC, [Q04, Q05])]
    model.events["note_04"] = [ev("note_04", 1, None, Q04)]  # overlaps the D01 quote: never drafted
    if not overlapping_only:  # same passage, no overlap
        model.events["note_04"].append(ev("note_04", 2, "CAP", (Q04[0], "Intravenous Antibiotic B.")))
    model.fails = {"note_04": 2}
    sid, sse, resumed = run(client, model)

    assert "note_retrying" not in [n for n, _ in sse]  # the load stream ends at the pause
    retrying, settles, rest = settled(resumed)
    assert retrying == ["note_04"] and settles["note_04"][0] == "note_extracted"
    first = drafts(resumed)[0]
    if overlapping_only:  # nothing changed: no section call, no dedupe, straight to done
        assert rest == ["done"]
        assert set(model.section_counts().values()) == {1} and len(model.dedupe) == 1
    else:
        assert rest[-3:] == ["dedupe_applied", "draft", "done"]
        assert model.section_counts()[(HC, "Pneumonia")] == 2 and model.section_counts()[(HC, "Other")] == 1
        hc_redraft = [m for s, p, m in model.summary if (s, p) == (HC, "Pneumonia")][1]
        redrafts = [m for s, p, m in model.summary if s != HC][len(NON_HC):]  # the first pass ran before the retry
        assert len(redrafts) == len(NON_HC)
        for m in [hc_redraft, *redrafts]:
            assert "note_04 fact 1" not in text_of(m) and "note_04 fact 2" in text_of(m)
        assert all(CLARIFICATION in text_of(m) for m in redrafts)  # resolutions reach the redraft as in 07-10
        assert "note_04 fact 2" in [t for _, _, t in rows(drafts(resumed)[-1]["draft"])]
    last = drafts(resumed)[-1]["draft"]
    assert last["discrepancies"] == first["draft"]["discrepancies"]
    assert [d["status"] for d in last["discrepancies"]] == ["clarified_pending_approval"]
    assert any("D01" in c["clinician_clarification_ids"] for c in last["claims"])
    s = state(client, sid)
    assert {"note_04 fact 1", "note_04 fact 2"} & {e["statement"] for e in s["events"]} == (
        {"note_04 fact 1"} if overlapping_only else {"note_04 fact 1", "note_04 fact 2"})
    assert s["missing_notes"] == [] and s["load_running"] is False


# ---------- redraft failure, new load ----------

def test_section_failing_during_the_redraft_fails_the_load(client, model):
    model.fails = {"note_02": 2}
    model.raising = {(HC, "Acute kidney injury")}  # a group that exists only after the retry
    sid, sse, _ = run(client, model)

    names = [n for n, _ in sse]
    assert names.count("draft") == 1 and "note_retrying" in names
    assert names[-1] == "error" and "done" not in names
    assert state(client, sid)["load_running"] is False


def test_a_new_load_resets_missing_notes(client, model):
    sid = create(client)
    assert state(client, sid)["missing_notes"] == []
    model.fails = {"note_05": float("inf")}
    run(client, model, sid)
    assert state(client, sid)["missing_notes"] == ["note_05"]

    model.fails = {}
    _, sse, _ = run(client, model, sid)
    assert sse[-1][0] == "done"
    assert state(client, sid)["missing_notes"] == []
