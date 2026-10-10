from pydantic import BaseModel, ConfigDict, Field


class CreateSession(BaseModel):
    case_id: str


class Ask(BaseModel):
    question: str = Field(pattern=r"\S")


class Propose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    statement: str


class Approve(BaseModel):
    reviewer: str = Field(pattern=r"\S")


class ResolutionIn(BaseModel):
    conflict_id: str
    chosen_span_id: str | None = None
    clarification: str | None = None


class Resolve(BaseModel):
    resolutions: list[ResolutionIn]
