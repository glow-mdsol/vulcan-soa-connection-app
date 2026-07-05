import httpx
import respx

from vulcan_soa.activity_flow import (
    VisitChain,
    activity_tag,
    context_from_chains,
    group_identifier,
    load_chains,
    parse_tag,
    visit_details,
    visit_tag,
)
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import schedule_response
from vulcan_soa.soa_engine.engine import ScheduleState


def test_tag_helpers_produce_identifier_dicts():
    assert visit_tag("pd-1", "E1") == {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1"}
    assert activity_tag("pd-1", "E1", "act-1") == {
        "system": "urn:vulcan-soa:plan-action",
        "value": "pd-1#E1#act-1",
    }
    assert group_identifier("pd-1", "E1", "plan") == {
        "system": "urn:vulcan-soa:promotion",
        "value": "pd-1#E1:plan",
    }


def test_parse_tag_splits_action_and_activity():
    assert parse_tag("pd-1#E1", "pd-1") == ("E1", None)
    assert parse_tag("pd-1#E1#act-1", "pd-1") == ("E1", "act-1")
    assert parse_tag("other-pd#E1", "pd-1") is None


def test_phase_derivation_walks_the_lifecycle():
    chain = VisitChain(action_id="E1")
    assert chain.phase == "proposed"

    chain.requests["plan"] = {"resourceType": "ServiceRequest", "intent": "plan"}
    assert chain.phase == "planned"

    chain.requests["order"] = {"resourceType": "ServiceRequest", "intent": "order"}
    assert chain.phase == "ordered"

    chain.appointment = {"resourceType": "Appointment", "status": "proposed"}
    assert chain.phase == "scheduled"

    chain.appointment["status"] = "booked"
    assert chain.phase == "booked"

    chain.encounter = {"resourceType": "Encounter", "status": "in-progress"}
    assert chain.phase == "performing"

    chain.encounter["status"] = "completed"
    assert chain.phase == "completed"


def test_context_from_chains_derives_visited_and_completed():
    chains = {
        "E1": VisitChain(action_id="E1", encounter={"status": "completed"}),
        "E2": VisitChain(action_id="E2", requests={"proposal": {}}),
    }
    subject = {"resourceType": "ResearchSubject", "status": "active"}

    context = context_from_chains(subject, chains)

    assert context.visited_action_ids == frozenset({"E1", "E2"})
    assert context.completed_action_ids == frozenset({"E1"})
    assert context.withdrawn is False

    retired = context_from_chains({"status": "retired"}, chains)
    assert retired.withdrawn is True


def test_visit_details_reports_phase_participants_and_tasks():
    chain = VisitChain(
        action_id="E1",
        requests={"proposal": {}, "plan": {}, "order": {}},
        appointment={
            "status": "proposed",
            "participant": [
                {"actor": {"reference": "Patient/p-1"}, "status": "accepted"},
                {"actor": {"reference": "Practitioner/site-coordinator-demo"}, "status": "needs-action"},
            ],
        },
        tasks=[{"id": "t-1", "description": "Vital signs", "status": "ready"}],
    )

    details = visit_details({"E1": chain})

    assert details["E1"]["phase"] == "scheduled"
    assert details["E1"]["participants"] == [
        {"role": "patient", "status": "accepted"},
        {"role": "site", "status": "needs-action"},
    ]
    assert details["E1"]["tasks"] == [{"id": "t-1", "description": "Vital signs", "status": "ready"}]


def test_schedule_response_includes_visits():
    state = ScheduleState(
        completed_action_ids=frozenset(), current_action_ids=frozenset(), next_steps=()
    )
    assert schedule_response(state)["visits"] == {}
    assert schedule_response(state, visits={"E1": {"phase": "proposed"}})["visits"] == {
        "E1": {"phase": "proposed"}
    }


def _bundle(*resources: dict) -> dict:
    return {"resourceType": "Bundle", "entry": [{"resource": r} for r in resources]}


@respx.mock
async def test_load_chains_groups_resources_by_action_and_activity():
    tag = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1"}
    activity = {"system": "urn:vulcan-soa:plan-action", "value": "pd-1#E1#act-1"}
    respx.get("http://aidbox.test/fhir/ServiceRequest").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {"resourceType": "ServiceRequest", "id": "sr-1", "intent": "proposal",
                 "status": "completed", "identifier": [tag]},
                {"resourceType": "ServiceRequest", "id": "sr-2", "intent": "plan",
                 "status": "active", "identifier": [tag]},
                {"resourceType": "ServiceRequest", "id": "sr-3", "intent": "proposal",
                 "status": "active", "identifier": [activity]},
                {"resourceType": "ServiceRequest", "id": "sr-x", "intent": "proposal",
                 "status": "active",
                 "identifier": [{"system": "urn:vulcan-soa:plan-action", "value": "other-pd#Z"}]},
            ),
        )
    )
    respx.get("http://aidbox.test/fhir/Appointment").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {"resourceType": "Appointment", "id": "appt-1", "status": "proposed",
                 "identifier": [tag],
                 "participant": [{"actor": {"reference": "Patient/p-1"}, "status": "needs-action"}]},
                {"resourceType": "Appointment", "id": "appt-other", "status": "proposed",
                 "identifier": [tag],
                 "participant": [{"actor": {"reference": "Patient/p-2"}, "status": "needs-action"}]},
            ),
        )
    )
    respx.get("http://aidbox.test/fhir/Encounter").mock(
        return_value=httpx.Response(200, json=_bundle())
    )
    respx.get("http://aidbox.test/fhir/Task").mock(
        return_value=httpx.Response(
            200,
            json=_bundle(
                {"resourceType": "Task", "id": "t-1", "status": "ready",
                 "for": {"reference": "Patient/p-1"}, "identifier": [activity]},
                {"resourceType": "Task", "id": "t-other", "status": "ready",
                 "for": {"reference": "Patient/p-2"}, "identifier": [activity]},
            ),
        )
    )

    client = FhirClient(base_url="http://aidbox.test/fhir", access_token="tok")
    chains = await load_chains(client, "p-1", "pd-1")
    await client.close()

    assert set(chains) == {"E1"}
    chain = chains["E1"]
    assert chain.requests["proposal"]["id"] == "sr-1"
    assert chain.requests["plan"]["id"] == "sr-2"
    assert chain.activities["act-1"]["proposal"]["id"] == "sr-3"
    assert chain.appointment["id"] == "appt-1"
    assert [t["id"] for t in chain.tasks] == ["t-1"]
    assert chain.phase == "scheduled"
