import json

import httpx
import respx

from vulcan_soa.activity_flow import respond, schedule_visit
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
ORDER = {
    "resourceType": "ServiceRequest", "id": "sr-order", "intent": "order", "status": "active",
    "subject": {"reference": "Patient/p-1"}, "identifier": [VISIT_TAG],
    "code": {"concept": {"text": "Screening 1"}},
}
PROPOSAL = dict(ORDER, id="sr-proposal", intent="proposal", status="completed")
PLAN = dict(ORDER, id="sr-plan", intent="plan", status="completed")


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
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(PROPOSAL, PLAN, ORDER))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )


@respx.mock
async def test_schedule_visit_creates_proposed_appointment_with_participants():
    _mock_subject_reads()
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    create_route = respx.post("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(201, json={"resourceType": "Appointment", "id": "appt-1"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await schedule_visit(client, "subj-1", "E1")
    await client.close()

    payload = json.loads(create_route.calls.last.request.content)
    assert payload["status"] == "proposed"
    assert payload["basedOn"] == [{"reference": "ServiceRequest/sr-order"}]
    assert payload["identifier"] == [VISIT_TAG]
    assert payload["participant"] == [
        {"actor": {"reference": "Patient/p-1"}, "status": "needs-action"},
        {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
    ]


@respx.mock
async def test_respond_accepts_participant_and_books_when_all_accepted():
    _mock_subject_reads()
    appointment = {
        "resourceType": "Appointment", "id": "appt-1", "status": "proposed",
        "identifier": [VISIT_TAG], "meta": {"versionId": "3"},
        "participant": [
            {"actor": {"reference": "Patient/p-1"}, "status": "accepted"},
            {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
        ],
    }
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(appointment))
    )
    response_route = respx.post("http://aidbox.test/fhir/AppointmentResponse").mock(
        return_value=httpx.Response(201, json={"resourceType": "AppointmentResponse", "id": "ar-1"})
    )
    update_route = respx.put("http://aidbox.test/fhir/Appointment/appt-1").mock(
        return_value=httpx.Response(200, json=dict(appointment, status="booked"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await respond(client, "subj-1", "E1", "site", "accepted")
    await client.close()

    response_payload = json.loads(response_route.calls.last.request.content)
    assert response_payload["appointment"] == {"reference": "Appointment/appt-1"}
    assert response_payload["actor"] == {"reference": "Practitioner/site-coordinator-demo"}
    assert response_payload["participantStatus"] == "accepted"

    appointment_payload = json.loads(update_route.calls.last.request.content)
    assert appointment_payload["status"] == "booked"
    assert appointment_payload["participant"][1]["status"] == "accepted"
    assert update_route.calls.last.request.headers["If-Match"] == 'W/"3"'


@respx.mock
async def test_respond_declined_keeps_appointment_proposed():
    _mock_subject_reads()
    appointment = {
        "resourceType": "Appointment", "id": "appt-1", "status": "proposed",
        "identifier": [VISIT_TAG],
        "participant": [
            {"actor": {"reference": "Patient/p-1"}, "status": "needs-action"},
            {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
        ],
    }
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(appointment))
    )
    respx.post("http://aidbox.test/fhir/AppointmentResponse").mock(
        return_value=httpx.Response(201, json={"resourceType": "AppointmentResponse", "id": "ar-1"})
    )
    update_route = respx.put("http://aidbox.test/fhir/Appointment/appt-1").mock(
        return_value=httpx.Response(200, json=appointment)
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await respond(client, "subj-1", "E1", "patient", "declined")
    await client.close()

    payload = json.loads(update_route.calls.last.request.content)
    assert payload["status"] == "proposed"
    assert payload["participant"][0]["status"] == "declined"
