from typing import Literal

from pydantic import BaseModel, Field


class EnrollRequest(BaseModel):
    patientId: str
    subjectIdentifier: str = Field(min_length=1)
    planDefinitionId: str | None = None


class AssignIdentifierRequest(BaseModel):
    subjectIdentifier: str = Field(min_length=1)


class RecordMilestoneRequest(BaseModel):
    milestone: str = Field(min_length=1)
    display: str | None = None
    date: str | None = None


class CompleteVisitRequest(BaseModel):
    transitionChoice: str | None = None


class RespondRequest(BaseModel):
    participant: Literal["patient", "site"]
    response: Literal["accepted", "declined"]
