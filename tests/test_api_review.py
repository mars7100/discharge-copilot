"""Regression tests for defects found in review of ticket 03a."""
import asyncio
import queue

import pytest

from api import sessions, streaming
from tests.test_api import ROOT, calls, client, create  # noqa: F401  (fixtures)


@pytest.mark.parametrize("case_id", ["..", ".", str(ROOT)])
def test_create_session_rejects_paths_outside_fixture_cases(client, case_id):
    assert client.post("/api/sessions", json={"case_id": case_id}).status_code == 404


@pytest.mark.parametrize("fail", [False, True])
def test_load_running_false_before_terminal_event(client, calls, fail):
    """A client reacting to `done`/`error` must already see load_running false."""
    sid = create(client)
    calls.fail = fail
    seen = []

    class Recording(queue.Queue):
        def put(self, item, *a, **k):
            if item is not streaming.DONE and item[0] in ("done", "error"):
                seen.append(sessions.state(sid)["load_running"])
            super().put(item, *a, **k)

    sessions.update(sid, load_running=True)
    streaming.run_load(sid, Recording())
    assert seen == [False]


def test_load_running_true_as_soon_as_load_is_accepted(client, calls):
    """No window after POST /load where a GET reports load_running false."""
    sid = create(client)
    gen = streaming.stream_load(sid)
    assert sessions.state(sid)["load_running"] is True

    async def drain():
        return [b async for b in gen]
    asyncio.run(drain())
    assert sessions.state(sid)["load_running"] is False
