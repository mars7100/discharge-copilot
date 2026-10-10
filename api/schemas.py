from pydantic import BaseModel, Field


class CreateSession(BaseModel):
    case_id: str


class Ask(BaseModel):
    question: str = Field(pattern=r"\S")


class Propose(BaseModel):
    claim_id: str
    after: str
    statement: str


class Approve(BaseModel):
    reviewer: str = Field(pattern=r"\S")


class ResolutionIn(BaseModel):
    conflict_id: str
    chosen_span_id: str | None = None
    clarification: str | None = None


class Resolve(BaseModel):
    resolutions: list[ResolutionIn]
