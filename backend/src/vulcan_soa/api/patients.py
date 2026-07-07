from fastapi import APIRouter, Depends

from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.models import EnrollRequest
from vulcan_soa.enrollment import enroll
from vulcan_soa.fhir_client import FhirClient
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/patients")


@router.get("")
async def list_patients(client: FhirClient = Depends(get_fhir_client)) -> list[dict]:
    patients = await client.search("Patient", {})
    logger.info("Retrieved %d patients from FHIR server.", len(patients))
    return [
        {"id": patient["id"], "gender": patient.get("gender"), "birthDate": patient.get("birthDate"), "deceased": patient.get("deceasedBoolean"), "active": patient.get("active")} for patient in patients
    ]


