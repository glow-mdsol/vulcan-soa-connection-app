from fastapi import APIRouter, Depends

from vulcan_soa.api.deps import get_current_session
from vulcan_soa.auth import Session

router = APIRouter(prefix="/api")


@router.get("/context")
async def get_context(session: Session = Depends(get_current_session)) -> dict:
    return {"patientId": session.patient_id, "researchStudyId": session.research_study_id}
