"""Regression tests for defects found in review of ticket 04."""
import threading
import time

from fastapi import HTTPException

import api.app
from api import sessions
from tests.test_api import calls, client  # noqa: F401  (fixtures)
from tests.test_api_ticket04 import claim_id, loaded, model_proposes, propose, proposer  # noqa: F401  (ticket 13: the stubbed model proposes)


def test_concurrent_accepts_resolve_the_pending_correction_once(client, calls, monkeypatch):
    """A double-clicked Accept: check-then-update must be atomic, or both requests append R01."""
    sid = loaded(client)
    propose(client, sid, claim_id(client, sid))
    real = api.app.accept
    monkeypatch.setattr(api.app, "accept", lambda d, r: (time.sleep(0.1), real(d, r))[1])
    errors = []

    def accept():
        try:
            api.app.accept_correction(sid, "R01")
        except HTTPException as e:
            errors.append(e.status_code)
    threads = [threading.Thread(target=accept) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [404]
    assert [r["revision_id"] for r in sessions.state(sid)["revisions"]] == ["R01"]
