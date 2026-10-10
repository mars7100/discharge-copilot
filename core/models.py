"""Pydantic contracts (spec §6). Cross-object checks (span IDs exist, quotes match) live in validate.py."""
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Document(BaseModel):
    document_id: str                # e.g. note_04
    filename: str
    date: str | None                # ISO date from note header
    hospital_day: int | None
    type: str | None
    author_role: str | None


class SourceSpan(BaseModel):
    span_id: str                    # e.g. note_04_p01_b03
    document_id: str
    filename: str
    page: int                       # 1-based; TXT notes are page 1
    order: int                      # passage sequence within document
    text: str                       # exact extracted passage, immutable


class EvidenceRef(BaseModel):
    span_id: str
    quote: str
    start: int | None = None        # char offset of quote in span text; LLM outputs null, validation fills it


class ClinicalEvent(BaseModel):
    event_id: str
    date_or_hospital_day: str | None
    category: Literal[
        "presentation", "assessment_documented", "treatment_documented",
        "test_result_documented", "status", "follow_up", "other",
    ]
    statement: str                  # documented fact, not model inference
    evidence: list[EvidenceRef] = Field(min_length=1)
    needs_review: bool = False
    problem: str | None = None      # clinical problem the event belongs to, as named in the note


class ConflictItem(BaseModel):
    conflict_id: str                # placeholder; renumbered D01.. at merge
    description: str
    quotes: list[EvidenceRef] = Field(min_length=2)  # one verbatim quote per conflicting passage


TEMPLATE = json.loads((Path(__file__).parent / "template.json").read_text())["sections"]  # in export order
Section = Literal[tuple(s["section_id"] for s in TEMPLATE)]


class SummaryClaim(BaseModel):
    claim_id: str
    section: Section
    text: str
    evidence_span_ids: list[str]
    clinician_clarification_ids: list[str] = []
    support_status: Literal["unverified", "supported", "needs_review"]


class Discrepancy(BaseModel):
    discrepancy_id: str
    description: str
    source_span_ids: list[str]
    status: Literal["open", "clarified_pending_approval", "reviewed"] = "open"


class ClinicianClarification(BaseModel):
    """Clinician statement; never document evidence (spec §6)."""
    clarification_id: str
    statement: str                  # transcript or typed input
    target_claim_id: str
    status: Literal["pending", "accepted", "rejected"] = "pending"


class ProposedRevision(BaseModel):
    revision_id: str
    target_claim_id: str
    before: str
    after: str
    clinician_statement: str        # transcript or typed input
    clarification_id: str           # links to ClinicianClarification
    source_span_ids: list[str] = []
    status: Literal["pending", "accepted", "rejected"] = "pending"


class Draft(BaseModel):
    claims: list[SummaryClaim]
    discrepancies: list[Discrepancy] = []
    status: Literal["draft", "approved"] = "draft"
    approved_at: datetime | None = None
    reviewer: str | None = None     # simulated reviewer label, never a signature
