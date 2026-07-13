from fastapi import APIRouter, Depends, HTTPException

from vulcan_soa.activity_flow import build_protocol_tree
from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.models import EnrollRequest
from vulcan_soa.enrollment import EnrollmentConflict, enroll, subject_summary
from vulcan_soa.fhir_client import FhirClient

router = APIRouter(prefix="/api/research-studies")


@router.get("")
async def list_research_studies(client: FhirClient = Depends(get_fhir_client)) -> list[dict]:
    studies = await client.search("ResearchStudy", {})
    return [
        {"id": study["id"], "title": study.get("title", study["id"])} for study in studies
    ]


@router.get("/{study_id}")
async def get_research_study(study_id: str, client: FhirClient = Depends(get_fhir_client)) -> dict:
    study = await client.read("ResearchStudy", study_id)
    return {
        "id": study["id"],
        "title": study.get("title", study["id"]),
        "status": study.get("status"),
        "protocolReferences": [
            protocol.get("reference")
            for protocol in study.get("protocol", [])
            if protocol.get("reference")
        ],
    }


@router.get("/{study_id}/subjects")
async def list_study_subjects(
    study_id: str, client: FhirClient = Depends(get_fhir_client)
) -> list[dict]:
    subjects = await client.search(
        "ResearchSubject", {"study": f"ResearchStudy/{study_id}"}
    )
    return [subject_summary(subject) for subject in subjects]


@router.get("/{study_id}/protocol-tree")
async def get_protocol_tree(
    study_id: str,
    planDefinitionId: str | None = None,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    try:
        return await build_protocol_tree(client, study_id, planDefinitionId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{study_id}/enroll")
async def enroll_patient(
    study_id: str, body: EnrollRequest, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    try:
        return await enroll(
            client, study_id, body.patientId, body.subjectIdentifier, body.planDefinitionId
        )
    except EnrollmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
