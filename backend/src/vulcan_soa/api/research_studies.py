from fastapi import APIRouter, Depends

from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.models import EnrollRequest
from vulcan_soa.enrollment import enroll
from vulcan_soa.fhir_client import FhirClient

router = APIRouter(prefix="/api/research-studies")


@router.get("")
async def list_research_studies(client: FhirClient = Depends(get_fhir_client)) -> list[dict]:
    studies = await client.search("ResearchStudy", {})
    return [
        {"id": study["id"], "title": study.get("title", study["id"])} for study in studies
    ]


@router.post("/{study_id}/enroll")
async def enroll_patient(
    study_id: str, body: EnrollRequest, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await enroll(client, study_id, body.patientId)
