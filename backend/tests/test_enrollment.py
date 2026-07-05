import json

import httpx
import respx

from vulcan_soa.enrollment import enroll
from vulcan_soa.fhir_client import FhirClient

STUDY = {
    "resourceType": "ResearchStudy",
    "id": "uc1-demo-research-study",
    "protocol": [{"reference": "PlanDefinition/plan-1"}],
}
PLAN_DEFINITION = {
    "resourceType": "PlanDefinition",
    "id": "plan-1",
    "action": [{"id": "screening-1", "title": "Screening"}],
}


@respx.mock
async def test_enroll_creates_subject_and_materializes_root_visit():
    respx.get("http://aidbox.test/fhir/ResearchStudy/uc1-demo-research-study").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    create_subject_route = respx.post("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(201, json={"resourceType": "ResearchSubject", "id": "subj-1"})
    )
    create_service_request_route = respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1")
    await client.close()

    assert result["researchSubjectId"] == "subj-1"
    assert result["schedule"]["nextSteps"] == []  # the root visit is materialized, not "next"
    assert result["schedule"]["visits"] == {"screening-1": {"phase": "proposed"}}
    assert create_subject_route.called
    assert create_service_request_route.called
    proposal_payload = json.loads(create_service_request_route.calls.last.request.content)
    assert proposal_payload["intent"] == "proposal"
    assert proposal_payload["identifier"] == [
        {"system": "urn:vulcan-soa:plan-action", "value": "plan-1#screening-1"}
    ]


@respx.mock
async def test_enroll_is_idempotent_via_conditional_create():
    respx.get("http://aidbox.test/fhir/ResearchStudy/uc1-demo-research-study").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    respx.get("http://aidbox.test/fhir/ResearchSubject").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [{"resource": {"resourceType": "ResearchSubject", "id": "subj-existing"}}],
            },
        )
    )
    create_subject_route = respx.post("http://aidbox.test/fhir/ResearchSubject")
    respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await enroll(client, "uc1-demo-research-study", "patient-1")
    await client.close()

    assert result["researchSubjectId"] == "subj-existing"
    assert not create_subject_route.called
