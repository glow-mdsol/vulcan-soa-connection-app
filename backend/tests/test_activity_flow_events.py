import json

import httpx
import pytest
import respx

from vulcan_soa.activity_flow import (
    PhaseError,
    VisitChain,
    complete,
    complete_task,
    perform,
    respond,
    revoke_open_workflow,
)
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
READY_TASK = {
    "resourceType": "Task", "id": "t-1", "status": "ready", "intent": "order",
    "identifier": [ACTIVITY_TAG], "meta": {"versionId": "1"},
    "basedOn": [{"reference": "ServiceRequest/sr-act-order"}],
    "focus": {"reference": "ServiceRequest/sr-act-order"},
    "for": {"reference": "Patient/p-1"},
    "encounter": {"reference": "Encounter/enc-1"},
    "description": "Informed Consent",
}
IN_PROGRESS_ENCOUNTER = {
    "resourceType": "Encounter", "id": "enc-1", "status": "in-progress",
    "meta": {"versionId": "2"}, "identifier": [VISIT_TAG],
    "subject": {"reference": "Patient/p-1"},
}


def _bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


def _mock_performing_chain(*, tasks=(READY_TASK,)):
    _mock_subject_reads()
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(VISIT_ORDER, ACTIVITY_ORDER))
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(BOOKED_APPOINTMENT))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER))
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle(*tasks))
    )


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


@respx.mock
async def test_complete_task_writes_procedure_and_completes_task():
    _mock_performing_chain()
    procedure_route = respx.post("http://aidbox.test/fhir/Procedure").mock(
        return_value=httpx.Response(201, json={"resourceType": "Procedure", "id": "proc-1"})
    )
    task_update = respx.put("http://aidbox.test/fhir/Task/t-1").mock(
        return_value=httpx.Response(200, json=dict(READY_TASK, status="completed"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await complete_task(client, "subj-1", "E1", "t-1")
    await client.close()

    procedure_payload = json.loads(procedure_route.calls.last.request.content)
    assert procedure_payload["status"] == "completed"
    assert procedure_payload["code"] == {"coding": [{"display": "Informed Consent"}]}
    assert procedure_payload["subject"] == {"reference": "Patient/p-1"}
    assert procedure_payload["encounter"] == {"reference": "Encounter/enc-1"}
    assert procedure_payload["basedOn"] == [{"reference": "ServiceRequest/sr-act-order"}]
    assert procedure_payload["identifier"] == [ACTIVITY_TAG]

    task_payload = json.loads(task_update.calls.last.request.content)
    assert task_payload["status"] == "completed"
    assert task_payload["output"] == [
        {"type": {"text": "procedure"}, "valueReference": {"reference": "Procedure/proc-1"}}
    ]


@respx.mock
async def test_complete_task_unknown_id_raises_value_error():
    _mock_performing_chain()

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(ValueError):
        await complete_task(client, "subj-1", "E1", "t-missing")
    await client.close()


@respx.mock
async def test_complete_sweeps_tasks_completes_requests_and_encounter():
    _mock_performing_chain()
    procedure_route = respx.post("http://aidbox.test/fhir/Procedure").mock(
        return_value=httpx.Response(201, json={"resourceType": "Procedure", "id": "proc-1"})
    )
    respx.put("http://aidbox.test/fhir/Task/t-1").mock(
        return_value=httpx.Response(200, json=dict(READY_TASK, status="completed"))
    )
    visit_order_update = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(VISIT_ORDER, status="completed"))
    )
    activity_order_update = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-act-order").mock(
        return_value=httpx.Response(200, json=dict(ACTIVITY_ORDER, status="completed"))
    )
    encounter_update = respx.put("http://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=dict(IN_PROGRESS_ENCOUNTER, status="completed"))
    )

    # Override the Encounter GET mock with side_effect list
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER)),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
        ]
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await complete(client, "subj-1", "E1", None)
    await client.close()

    assert procedure_route.called
    assert json.loads(visit_order_update.calls.last.request.content)["status"] == "completed"
    assert json.loads(activity_order_update.calls.last.request.content)["status"] == "completed"
    assert json.loads(encounter_update.calls.last.request.content)["status"] == "completed"
    assert result["completed"] == ["E1"]


@respx.mock
async def test_complete_skips_already_completed_and_cancelled_tasks():
    _mock_performing_chain(
        tasks=(
            READY_TASK,
            dict(READY_TASK, id="t-2", status="completed"),
            dict(READY_TASK, id="t-3", status="cancelled"),
        )
    )
    procedure_route = respx.post("http://aidbox.test/fhir/Procedure").mock(
        return_value=httpx.Response(201, json={"resourceType": "Procedure", "id": "proc-1"})
    )
    # Only t-1 is mocked for update; respx raises on any unmocked PUT, so an
    # attempted update of t-2 or t-3 would fail the test.
    task_update = respx.put("http://aidbox.test/fhir/Task/t-1").mock(
        return_value=httpx.Response(200, json=dict(READY_TASK, status="completed"))
    )
    respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(VISIT_ORDER, status="completed"))
    )
    respx.put("http://aidbox.test/fhir/ServiceRequest/sr-act-order").mock(
        return_value=httpx.Response(200, json=dict(ACTIVITY_ORDER, status="completed"))
    )
    respx.put("http://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=dict(IN_PROGRESS_ENCOUNTER, status="completed"))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER)),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
        ]
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await complete(client, "subj-1", "E1", None)
    await client.close()

    assert procedure_route.call_count == 1
    assert task_update.called


AMBIGUOUS_PROTOCOL_PD = {
    "resourceType": "PlanDefinition",
    "id": "pd-1",
    "action": [
        {
            "id": "E1",
            "title": "Screening 1",
            "action": [
                {"extension": [{"url": "http://example.org/br-and-r/soa/StructureDefinition/soaTransition",
                                "extension": [{"url": "soaTargetId", "valueString": "E2"},
                                              {"url": "soaTransitionType", "valueString": "SS"}]}]},
                {"extension": [{"url": "http://example.org/br-and-r/soa/StructureDefinition/soaTransition",
                                "extension": [{"url": "soaTargetId", "valueString": "E3"},
                                              {"url": "soaTransitionType", "valueString": "SS"}]}]},
            ],
        },
        {"id": "E2", "title": "Branch A"},
        {"id": "E3", "title": "Branch B"},
    ],
}

E3_PROPOSAL = {
    "resourceType": "ServiceRequest", "id": "sr-e3", "intent": "proposal", "status": "active",
    "subject": {"reference": "Patient/p-1"},
    "identifier": [{"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E3"}],
    "code": {"concept": {"text": "Branch B"}},
}


@respx.mock
async def test_complete_with_transition_choice_materializes_chosen_proposal():
    respx.get("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/pd-1").mock(
        return_value=httpx.Response(200, json=AMBIGUOUS_PROTOCOL_PD)
    )
    # The third ServiceRequest search (the final recompute) sees the freshly
    # materialized E3 proposal alongside the completed E1 order.
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(VISIT_ORDER)),
            httpx.Response(200, json=_bundle(VISIT_ORDER)),
            httpx.Response(200, json=_bundle(VISIT_ORDER, E3_PROPOSAL)),
        ]
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(BOOKED_APPOINTMENT))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER)),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
            httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed"))),
        ]
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(VISIT_ORDER, status="completed"))
    )
    respx.put("http://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=dict(IN_PROGRESS_ENCOUNTER, status="completed"))
    )
    create_route = respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-e3"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    result = await complete(client, "subj-1", "E1", "E3")
    await client.close()

    payload = json.loads(create_route.calls.last.request.content)
    assert payload["intent"] == "proposal"
    assert payload["identifier"] == [{"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E3"}]
    # The returned state is recomputed AFTER materializing E3: it is now current,
    # so only E2 remains as a next step and the choice is no longer ambiguous.
    assert result["ambiguous"] is False
    assert "E3" in result["current"]
    assert {s["actionId"] for s in result["nextSteps"]} == {"E2"}


@respx.mock
async def test_complete_ambiguous_then_choice_two_calls():
    # Regression for the ambiguous-choice re-entry: the first /complete returns
    # ambiguous with nothing materialized; the second /complete (with the chosen
    # branch) must succeed even though the Encounter is already completed.
    respx.get("http://aidbox.test/fhir/ResearchSubject/subj-1").mock(
        return_value=httpx.Response(200, json=SUBJECT)
    )
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(200, json=STUDY)
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/pd-1").mock(
        return_value=httpx.Response(200, json=AMBIGUOUS_PROTOCOL_PD)
    )
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(VISIT_ORDER)),  # call 1: load_workspace
            httpx.Response(200, json=_bundle(VISIT_ORDER)),  # call 1: reload
            httpx.Response(200, json=_bundle(VISIT_ORDER)),  # call 1: final
            httpx.Response(200, json=_bundle(VISIT_ORDER)),  # call 2: load_workspace
            httpx.Response(200, json=_bundle(VISIT_ORDER)),  # call 2: reload
            httpx.Response(200, json=_bundle(VISIT_ORDER, E3_PROPOSAL)),  # call 2: final
        ]
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(BOOKED_APPOINTMENT))
    )
    # First GET (call 1 load_workspace) is in-progress; every later load sees the
    # completed Encounter, which is what drives the re-entry branch on call 2.
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        side_effect=[
            httpx.Response(200, json=_bundle(IN_PROGRESS_ENCOUNTER)),
            *[
                httpx.Response(200, json=_bundle(dict(IN_PROGRESS_ENCOUNTER, status="completed")))
                for _ in range(5)
            ],
        ]
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(VISIT_ORDER, status="completed"))
    )
    respx.put("http://aidbox.test/fhir/Encounter/enc-1").mock(
        return_value=httpx.Response(200, json=dict(IN_PROGRESS_ENCOUNTER, status="completed"))
    )
    create_route = respx.post("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(201, json={"resourceType": "ServiceRequest", "id": "sr-e3"})
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")

    first = await complete(client, "subj-1", "E1", None)
    assert first["ambiguous"] is True
    assert {s["actionId"] for s in first["nextSteps"]} == {"E2", "E3"}
    assert create_route.call_count == 0  # nothing materialized yet

    # Second call must not raise PhaseError even though the Encounter is completed.
    second = await complete(client, "subj-1", "E1", "E3")
    await client.close()

    assert create_route.call_count == 1
    payload = json.loads(create_route.calls.last.request.content)
    assert payload["identifier"] == [{"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E3"}]
    assert second["ambiguous"] is False
    assert "E3" in second["current"]


def test_visit_chain_with_revoked_order_derives_revoked():
    chain = VisitChain(action_id="E1", requests={"order": dict(VISIT_ORDER, status="revoked")})
    assert chain.phase == "revoked"


@respx.mock
async def test_respond_on_cancelled_appointment_raises_phase_error():
    cancelled_appointment = dict(BOOKED_APPOINTMENT, status="cancelled")
    _mock_subject_reads()
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(VISIT_ORDER))
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(cancelled_appointment))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle())
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    with pytest.raises(PhaseError):
        await respond(client, "subj-1", "E1", "patient", "accepted")
    await client.close()


@respx.mock
async def test_revoke_open_workflow_revokes_and_cancels():
    active_order = dict(VISIT_ORDER, meta={"versionId": "1"})
    proposed_appointment = {
        "resourceType": "Appointment", "id": "appt-1", "status": "proposed",
        "identifier": [VISIT_TAG], "meta": {"versionId": "1"},
        "participant": [{"actor": {"reference": "Patient/p-1"}, "status": "needs-action"}],
    }
    ready_task = dict(READY_TASK)
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(200, json=_bundle(active_order))
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(200, json=_bundle(proposed_appointment))
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(200, json=_bundle(ready_task))
    )
    request_update = respx.put("http://aidbox.test/fhir/ServiceRequest/sr-visit-order").mock(
        return_value=httpx.Response(200, json=dict(active_order, status="revoked"))
    )
    appointment_update = respx.put("http://aidbox.test/fhir/Appointment/appt-1").mock(
        return_value=httpx.Response(200, json=dict(proposed_appointment, status="cancelled"))
    )
    task_update = respx.put("http://aidbox.test/fhir/Task/t-1").mock(
        return_value=httpx.Response(200, json=dict(ready_task, status="cancelled"))
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    await revoke_open_workflow(client, "p-1", "pd-1")
    await client.close()

    assert json.loads(request_update.calls.last.request.content)["status"] == "revoked"
    assert json.loads(appointment_update.calls.last.request.content)["status"] == "cancelled"
    assert json.loads(task_update.calls.last.request.content)["status"] == "cancelled"
