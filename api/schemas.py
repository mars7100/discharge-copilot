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
