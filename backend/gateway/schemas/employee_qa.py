# Request/response schemas for employee HR question answering
from pydantic import BaseModel, ConfigDict, Field


class StaffLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)  # the assistant enforces its own, lower limit


class Escalation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact: str | None = Field(default=None, max_length=120)


class Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
