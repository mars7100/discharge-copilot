"""Specification tests for ticket 03b backend: GET /api/template and the single-page-app mount.

Seam: api/app.py reads the built UI directory from env var DISCHARGE_UI_DIR at import time
(default frontend/dist). Tests point it at a temp dir and reload the module.
"""
import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
INDEX = "<!doctype html><div id='root'>discharge-ui</div>"


def app_with_ui_dir(monkeypatch, ui_dir: Path) -> TestClient:
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("DISCHARGE_UI_DIR", str(ui_dir))
    import api.app
    return TestClient(importlib.reload(api.app).app)


@pytest.fixture(autouse=True)
def restore_app():
    """Reload api.app after each test so other test modules get the default app."""
    yield
    import api.app
    importlib.reload(api.app)


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets" / "app.js").write_text("console.log('ui')")
    return tmp_path


def test_template_returns_sections_in_template_order(monkeypatch, dist):
    client = app_with_ui_dir(monkeypatch, dist)
    r = client.get("/api/template")
    assert r.status_code == 200
    assert r.json() == {"sections": json.loads((ROOT / "core" / "template.json").read_text())["sections"]}


def test_root_and_client_route_serve_index(monkeypatch, dist):
    client = app_with_ui_dir(monkeypatch, dist)
    for path in ("/", "/some/page"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert r.text == INDEX, path


def test_existing_built_file_is_served(monkeypatch, dist):
    r = app_with_ui_dir(monkeypatch, dist).get("/assets/app.js")
    assert r.status_code == 200 and r.text == "console.log('ui')"


def test_unknown_api_path_is_404_not_index(monkeypatch, dist):
    client = app_with_ui_dir(monkeypatch, dist)
    for path in ("/api/nope", "/api/sessions/x/nope"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert "discharge-ui" not in r.text, path


def test_api_routes_still_win_over_the_mount(monkeypatch, dist):
    r = app_with_ui_dir(monkeypatch, dist).get("/api/cases")
    assert r.status_code == 200 and "case_001" in r.json()["cases"]


def test_app_works_without_dist_dir(monkeypatch, tmp_path):
    client = app_with_ui_dir(monkeypatch, tmp_path / "missing")
    assert client.get("/api/cases").status_code == 200
    assert client.get("/api/template").status_code == 200
    assert client.get("/").status_code == 404
