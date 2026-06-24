import json

import httpx
import respx

from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import (
    ACTION_TAG_SYSTEM,
    load_protocol_graph,
    load_subject_context,
    materialize_visit,
    schedule_response,
    tag_for,
)
from vulcan_soa.soa_engine.engine import NextStep, ScheduleState
from vulcan_soa.soa_engine.graph import VisitNode


def test_tag_for_combines_plan_and_action_id():
    assert tag_for("plan-1", "action-1") == {
        "system": ACTION_TAG_SYSTEM,
        "value": "plan-1#action-1",
    }


@respx.mock
async def test_materialize_visit_creates_tagged_planned_encounter():
    route = respx.post("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(201, json={"resourceType": "Encounter", "id": "enc-1"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    node = VisitNode(action_id="action-1", title="Screening", transitions=())

    result = await materialize_visit(client, "patient-1", "plan-1", node)
    await client.close()

    assert result["id"] == "enc-1"
    payload = json.loads(route.calls.last.request.content)
    assert payload["status"] == "planned"
    assert payload["subject"] == {"reference": "Patient/patient-1"}
    assert payload["identifier"] == [{"system": ACTION_TAG_SYSTEM, "value": "plan-1#action-1"}]


@respx.mock
async def test_load_subject_context_reads_withdrawn_state_and_encounters():
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [
                    {
                        "resource": {
                            "resourceType": "Encounter",
                            "id": "enc-1",
                            "status": "finished",
                            "identifier": [
                                {"system": ACTION_TAG_SYSTEM, "value": "plan-1#action-1"}
                            ],
                        }
                    },
                    {
                        "resource": {
                            "resourceType": "Encounter",
                            "id": "enc-2",
                            "status": "planned",
                            "identifier": [
                                {"system": ACTION_TAG_SYSTEM, "value": "plan-1#action-2"}
                            ],
                        }
                    },
                ],
            },
        )
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    subject = {
        "resourceType": "ResearchSubject",
        "subjectState": {"coding": [{"code": "withdrawn"}]},
        "subject": {"reference": "Patient/patient-1"},
    }

    context, by_action_id = await load_subject_context(client, subject, "plan-1")
    await client.close()

    assert context.withdrawn is True
    assert context.visited_action_ids == frozenset({"action-1", "action-2"})
    assert context.completed_action_ids == frozenset({"action-1"})
    assert by_action_id["action-1"]["id"] == "enc-1"


@respx.mock
async def test_load_subject_context_not_withdrawn_when_state_differs():
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json={"resourceType": "Bundle"})
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    subject = {
        "resourceType": "ResearchSubject",
        "subjectState": {"coding": [{"code": "on-study"}]},
        "subject": {"reference": "Patient/patient-1"},
    }

    context, by_action_id = await load_subject_context(client, subject, "plan-1")
    await client.close()

    assert context.withdrawn is False
    assert context.visited_action_ids == frozenset()
    assert by_action_id == {}


@respx.mock
async def test_load_protocol_graph_reads_study_then_plan_definition():
    respx.get("http://aidbox.test/fhir/ResearchStudy/study-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "ResearchStudy",
                "id": "study-1",
                "protocol": [{"reference": "PlanDefinition/plan-1"}],
            },
        )
    )
    respx.get("http://aidbox.test/fhir/PlanDefinition/plan-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "resourceType": "PlanDefinition",
                "id": "plan-1",
                "action": [{"id": "action-1", "title": "Screening"}],
            },
        )
    )
    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")

    graph, plan_definition_id = await load_protocol_graph(client, "study-1")
    await client.close()

    assert plan_definition_id == "plan-1"
    assert graph.root_ids == ("action-1",)


def test_schedule_response_shapes_state_and_flags_ambiguous():
    state = ScheduleState(
        completed_action_ids=frozenset({"a"}),
        current_action_ids=frozenset(),
        next_steps=(
            NextStep(action_id="b", title="Day 7", transition_type="SS"),
            NextStep(action_id="c", title="End of Study", transition_type="FS"),
        ),
    )
    response = schedule_response(state)

    assert response["completed"] == ["a"]
    assert response["nextSteps"] == [
        {"actionId": "b", "title": "Day 7", "transitionType": "SS"},
        {"actionId": "c", "title": "End of Study", "transitionType": "FS"},
    ]
    assert response["ambiguous"] is True


def test_schedule_response_not_ambiguous_for_single_next_step():
    state = ScheduleState(
        completed_action_ids=frozenset(),
        current_action_ids=frozenset(),
        next_steps=(NextStep(action_id="a", title="Screening", transition_type=None),),
    )
    assert schedule_response(state)["ambiguous"] is False
