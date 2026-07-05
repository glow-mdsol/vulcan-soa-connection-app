from typing import Literal

from pydantic import BaseModel


class EnrollRequest(BaseModel):
    patientId: str


class CompleteVisitRequest(BaseModel):
    transitionChoice: str | None = None


class RespondRequest(BaseModel):
    participant: Literal["patient", "site"]
    response: Literal["accepted", "declined"]
