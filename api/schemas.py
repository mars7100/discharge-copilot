from pydantic import BaseModel


class CreateSession(BaseModel):
    case_id: str
