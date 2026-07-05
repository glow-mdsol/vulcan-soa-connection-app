import os
from pathlib import Path

import pytest

from scripts.load_fixtures import load_directory
from vulcan_soa.activity_flow import (
    complete,
    complete_task,
    load_chains,
    perform,
    promote,
    respond,
    schedule_visit,
)
from vulcan_soa.config import Settings
from vulcan_soa.enrollment import enroll
from vulcan_soa.fhir_client import FhirClient

SOA_IG_RESOURCES_DIR = Path(
    os.environ.get(
        "SOA_IG_RESOURCES_DIR",
        "/Users/GLW1/Documents/Devel/phuseorg/fhir-schedule-of-activities-ig/fsh-generated/resources",
    )
)
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

STUDY_ID = "lzzt-usdm-demo-study"
PATIENT_ID = "uc1-demo-patient"
PROTOCOL_PD_ID = "H2Q-MC-LZZT-ProtocolDesign-USDM"

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="requires a real local Aidbox with the WIP SoA IG loaded; set RUN_INTEGRATION_TESTS=1",
)


@pytest.fixture
async def client():
    settings = Settings()
    fhir_client = FhirClient(
        base_url=settings.fhir_base_url,
        basic_auth=(settings.smart_client_id, settings.smart_client_secret),
    )
    await load_directory(fhir_client, SOA_IG_RESOURCES_DIR)
    await load_directory(fhir_client, FIXTURES_DIR)
    yield fhir_client
    await fhir_client.close()


async def test_cpg_lifecycle_for_first_usdm_visit(client):
    enroll_result = await enroll(client, STUDY_ID, PATIENT_ID)
    subject_id = enroll_result["researchSubjectId"]
    visits = enroll_result["schedule"]["visits"]
    assert visits, "enroll should materialize at least one proposal"
    action_id = next(iter(visits))
    assert visits[action_id]["phase"] == "proposed"

    after_plan = await promote(client, subject_id, action_id, "plan")
    assert after_plan["visits"][action_id]["phase"] == "planned"

    after_order = await promote(client, subject_id, action_id, "order")
    assert after_order["visits"][action_id]["phase"] == "ordered"

    after_schedule = await schedule_visit(client, subject_id, action_id)
    assert after_schedule["visits"][action_id]["phase"] == "scheduled"

    await respond(client, subject_id, action_id, "patient", "accepted")
    after_site = await respond(client, subject_id, action_id, "site", "accepted")
    assert after_site["visits"][action_id]["phase"] == "booked"

    after_perform = await perform(client, subject_id, action_id)
    detail = after_perform["visits"][action_id]
    assert detail["phase"] == "performing"
    assert detail["tasks"], "E1 should have activity tasks"

    first_task = detail["tasks"][0]
    after_task = await complete_task(client, subject_id, action_id, first_task["id"])
    ticked = [t for t in after_task["visits"][action_id]["tasks"] if t["id"] == first_task["id"]]
    assert ticked[0]["status"] == "completed"

    after_complete = await complete(client, subject_id, action_id, None)
    assert action_id in after_complete["completed"]
    # Regression for the stale pre-materialization state: the next visit's
    # freshly materialized proposal must appear in `current` (unless the next
    # step was ambiguous, in which case nothing is materialized yet).
    if not after_complete["ambiguous"]:
        assert after_complete["current"], "the next visit should be current after completion"
        for step in after_complete["nextSteps"]:
            assert step["actionId"] not in after_complete["current"]
        materialized = set(after_complete["current"]) - {action_id}
        assert materialized, "a next-step proposal should be materialized into current"

    chains = await load_chains(client, PATIENT_ID, PROTOCOL_PD_ID)
    assert chains[action_id].phase == "completed"
    # basedOn chain is inspectable: order basedOn plan basedOn proposal
    order = chains[action_id].requests["order"]
    assert order["basedOn"][0]["reference"].startswith("ServiceRequest/")
