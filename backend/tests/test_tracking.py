import json

import httpx
import respx

from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.tracking import complete_visit, withdraw_subject

SUBJECT = {
    "resourceType": "ResearchSubject",
    "id": "subj-1",
    # R6: status (PublicationStatus) is "active" for an active subject
    "status": "active",
    "study": {"reference": "ResearchStudy/study-1"},
    "subject": {"reference": "Patient/patient-1"},
}
STUDY = {
    "resourceType": "ResearchStudy",
    "id": "study-1",
    "protocol": [{"reference": "PlanDefinition/plan-1"}],
}
PLAN_DEFINITION = {
    "resourceType": "PlanDefinition",
    "id": "plan-1",
    "action": [
        {
            "id": "screening-1",
            "title": "Screening",
            "action": [
                {
                    "extension": [
                        {
                            "url": "http://hl7.org/fhir/uv/vulcan-schedule/StructureDefinition/soaTransition",
                            "extension": [
                                {"url": "soaTargetId", "valueString": "treatment-1"},
                                {"url": "soaTransitionType", "valueString": "SS"},
                            ],
                        }
                    ]
                }
            ],
        },
        {"id": "treatment-1", "title": "Treatment Day 1"},
    ],
}
SCREENING_ENCOUNTER = {
    "resourceType": "Encounter",
    "id": "enc-1",
    "status": "planned",
    "meta": {"versionId": "1"},
    "identifier": [{"system": "urn:vulcan-soa:plan-action", "value": "plan-1#screening-1"}],
}


@respx.mock
async def test_withdraw_subject_updates_subject_state():
    respx.get("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=dict(SUBJECT, meta={"versionId": "5"}))
    )
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    for resource_type in ("ServiceRequest", "Appointment", "Encounter", "Task"):
        respx.get(f"http://aidbox.test/fhir/{resource_type}").mock(
            return_value=httpx.Response(200, json={"resourceType": "Bundle"})
        )
    update_route = respx.put("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ResearchSubject",
                "id": "subj-1",
                # R6: withdrawn subjects get status "retired"
                "status": "retired",
            },
        )
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await withdraw_subject(client, "subj-1")
    await client.close()

    assert result == {"id": "subj-1", "subjectState": "withdrawn"}
    assert update_route.calls.last.request.headers["If-Match"] == 'W/"5"'
    payload = json.loads(update_route.calls.last.request.content)
    # R6: withdrawal sets status to "retired"
    assert payload["status"] == "retired"
    # and appends an off-study entry to subjectState array
    assert any(
        entry.get("code", {}).get("coding", [{}])[0].get("code") == "off-study"
        for entry in payload.get("subjectState", [])
    )


@respx.mock
async def test_complete_visit_marks_finished_and_materializes_single_next_step():
    respx.get("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    finished_encounter = dict(SCREENING_ENCOUNTER, status="completed")
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": SCREENING_ENCOUNTER}]}),
            httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": finished_encounter}]}),
        ]
    )
    update_route = respx.put("http://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=dict(SCREENING_ENCOUNTER, status="completed"))
    )
    create_route = respx.post("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(201, json={"resourceType": "Encounter", "id": "enc-2"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await complete_visit(client, "subj-1", "screening-1", None)
    await client.close()

    assert update_route.called
    assert json.loads(update_route.calls.last.request.content)["status"] == "completed"
    assert create_route.called
    new_encounter_payload = json.loads(create_route.calls.last.request.content)
    assert new_encounter_payload["identifier"] == [
        {"system": "urn:vulcan-soa:plan-action", "value": "plan-1#treatment-1"}
    ]
    assert result["completed"] == ["screening-1"]


@respx.mock
async def test_complete_visit_raises_when_action_not_materialized():
    respx.get("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(200, json=PLAN_DEFINITION)
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    try:
        await complete_visit(client, "subj-1", "screening-1", None)
        raised = False
    except ValueError:
        raised = True
    await client.close()

    assert raised
