from pydantic import BaseModel


class EnrollRequest(BaseModel):
    patientId: str


class CompleteVisitRequest(BaseModel):
    transitionChoice: str | None = None
