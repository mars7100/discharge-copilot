"""Word download contract and existing Markdown compatibility."""
from datetime import datetime
from io import BytesIO

from docx import Document as WordDocument
from fastapi.testclient import TestClient

from api import sessions
from api.app import app
from core.models import Draft


def test_word_download_gate_headers_content_and_markdown_compatibility() -> None:
    """Exercise the shared gate and reopen an approved response as a Word document."""
    client = TestClient(app)
    assert client.get("/api/sessions/unknown-docx/export?format=docx").status_code == 404
    sid = sessions.create("case_001")
    url = f"/api/sessions/{sid}/export"
    assert client.get(url + "?format=docx").status_code == 409
    draft = Draft(claims=[])
    sessions.update(sid, draft=draft, load_running=True)
    assert client.get(url + "?format=docx").json()["detail"] == "load running"
    sessions.update(sid, load_running=False)
    assert client.get(url + "?format=docx").json()["detail"] == "not approved"
    sessions.update(sid, draft=draft.model_copy(update={"status": "approved", "reviewer": "Word reviewer",
                                                      "approved_at": datetime(2026, 1, 2, 12, 30)}))
    result = client.get(url + "?format=docx")
    assert result.status_code == 200
    assert result.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert result.headers["content-disposition"] == 'attachment; filename="discharge_summary_case_001.docx"'
    text = "\n".join(p.text for p in WordDocument(BytesIO(result.content)).paragraphs)
    assert "APPROVED by Word reviewer at 2026-01-02 12:30" in text
    markdown = client.get(url)
    assert markdown.status_code == 200 and markdown.text.startswith("# Discharge summary")
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.headers["content-disposition"].endswith('.md"')
    assert client.get(url + "?format=pdf").status_code == 422
