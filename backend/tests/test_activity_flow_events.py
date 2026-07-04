import json

import httpx
import respx

from vulcan_soa.activity_flow import perform
from vulcan_soa.fhir_client import FhirClient

SUBJECT = {
    "resourceType": "ResearchSubject",
    "id": "subj-1",
    "status": "active",
    "study": {"reference": "ResearchStudy/study-1"},
    "subject": {"reference": "Patient/p-1"},
}
STUDY = {
    "resourceType": "ResearchStudy",
    "id": "study-1",
    "protocol": [{"reference": "PlanDefinition/pd-1"}],
}
PROTOCOL_PD = {
    "resourceType": "PlanDefinition",
    "id": "pd-1",
    "action": [{"id": "E1", "title": "Screening 1"}],
}
VISIT_TAG = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1"}
ACTIVITY_TAG = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1#act-consent"}
VISIT_ORDER = {
    "resourceType": "ServiceRequest", "id": "sr-visit-order", "intent": "order", "status": "active",
    "subject": {"reference": "Patient/p-1"}, "identifier": [VISIT_TAG],
    "code": {"concept": {"text": "Screening 1"}},
}
ACTIVITY_ORDER = {
    "resourceType": "ServiceRequest", "id": "sr-act-order", "intent": "order", "status": "active",
    "subject": {"reference": "Patient/p-1"}, "identifier": [ACTIVITY_TAG],
    "code": {"concept": {"coding": [{"display": "Informed Consent"}]}},
}
BOOKED_APPOINTMENT = {
    "resourceType": "Appointment", "id": "appt-1", "status": "booked",
    "identifier": [VISIT_TAG],
    "participant": [
        {"actor": {"reference": "Patient/p-1"}, "status": "accepted"},
        {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "accepted"},
    ],
}


def _bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


def _mock_subject_reads():
    respx.get("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/pd-1").mock(
        return_value=httpx.Response(200, json=PROTOCOL_PD)
    )


@respx.mock
async def test_perform_creates_encounter_and_ready_tasks():
    _mock_subject_reads()
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(VISIT_ORDER, ACTIVITY_ORDER))
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(BOOKED_APPOINTMENT))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    encounter_route = respx.post("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(201, json={"resourceType": "Encounter", "id": "enc-1"})
    )
    task_route = respx.post("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(201, json={"resourceType": "Task", "id": "t-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await perform(client, "subj-1", "E1")
    await client.close()

    encounter_payload = json.loads(encounter_route.calls.last.request.content)
    assert encounter_payload["status"] == "in-progress"
    assert encounter_payload["appointment"] == [{"reference": "Appointment/appt-1"}]
    assert encounter_payload["basedOn"] == [{"reference": "ServiceRequest/sr-visit-order"}]
    assert encounter_payload["identifier"] == [VISIT_TAG]

    task_payload = json.loads(task_route.calls.last.request.content)
    assert task_payload["status"] == "ready"
    assert task_payload["intent"] == "order"
    assert task_payload["identifier"] == [ACTIVITY_TAG]
    assert task_payload["basedOn"] == [{"reference": "ServiceRequest/sr-act-order"}]
    assert task_payload["focus"] == {"reference": "ServiceRequest/sr-act-order"}
    assert task_payload["for"] == {"reference": "Patient/p-1"}
    assert task_payload["encounter"] == {"reference": "Encounter/enc-1"}
    assert task_payload["description"] == "Informed Consent"
