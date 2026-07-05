import os
from pathlib import Path

import pytest

from scripts.load_fixtures import load_directory
from vulcan_soa.activity_flow import (
    complete,
    perform,
    promote,
    respond,
    schedule_visit,
)
from vulcan_soa.config import Settings
from vulcan_soa.enrollment import enroll
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.tracking import withdraw_subject

IG_OUTPUT_DIR = Path(
    os.environ.get(
        "VULCAN_IG_OUTPUT_DIR",
        "/Users/GLW1/Documents/Devel/hl7/Vulcan-schedule-ig/output",
    )
)
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

STUDY_ID = "uc1-demo-research-study"
PATIENT_ID = "uc1-demo-patient"

SCREENING_ID = "0700e721-1f12-4998-89b8-6f4e649b62f7"
TREATMENT_DAY1_ID = "a1806239-54f3-4762-af3f-edb9d80d29dc"
DAY7_ID = "349447c3-8ad4-4034-8c31-c3d96dcc5f9a"
EOS_ID = "dbc35dee-a5f2-473f-b9b1-bb14b2a1c9ef"

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="requires a real local Aidbox with the IG and this plan's fixtures loaded; set RUN_INTEGRATION_TESTS=1 to run",
)


@pytest.fixture
async def client():
    settings = Settings()
    fhir_client = FhirClient(
        base_url=settings.fhir_base_url,
        basic_auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    await load_directory(fhir_client, IG_OUTPUT_DIR)
    await load_directory(fhir_client, FIXTURES_DIR)
    yield fhir_client
    await fhir_client.close()


async def _walk_to_performing(client: FhirClient, subject_id: str, action_id: str) -> None:
    await promote(client, subject_id, action_id, "plan")
    await promote(client, subject_id, action_id, "order")
    await schedule_visit(client, subject_id, action_id)
    await respond(client, subject_id, action_id, "patient", "accepted")
    await respond(client, subject_id, action_id, "site", "accepted")
    await perform(client, subject_id, action_id)


async def test_golden_path_enroll_progress_withdraw_ambiguous(client):
    enroll_result = await enroll(client, STUDY_ID, PATIENT_ID)
    subject_id = enroll_result["researchSubjectId"]
    assert enroll_result["schedule"]["nextSteps"] == []

    await _walk_to_performing(client, subject_id, SCREENING_ID)
    after_screening = await complete(client, subject_id, SCREENING_ID, None)
    assert [s["actionId"] for s in after_screening["nextSteps"]] == [TREATMENT_DAY1_ID]
    assert after_screening["ambiguous"] is False

    await _walk_to_performing(client, subject_id, TREATMENT_DAY1_ID)
    await withdraw_subject(client, subject_id)

    after_treatment_day1 = await complete(client, subject_id, TREATMENT_DAY1_ID, None)
    target_ids = {s["actionId"] for s in after_treatment_day1["nextSteps"]}
    assert target_ids == {DAY7_ID, EOS_ID}
    assert after_treatment_day1["ambiguous"] is True
