import datetime

from vulcan_soa.activity_flow import revoke_open_workflow
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import (
    load_protocol_graph_for_subject,
    load_subject_context,
    materialize_visit,
    schedule_response,
)
from vulcan_soa.soa_engine.engine import resolve_schedule_state

RESEARCH_SUBJECT_STATE_SYSTEM = "http://terminology.hl7.org/CodeSystem/research-subject-state"


def _today() -> str:
    return datetime.date.today().isoformat()


def _if_match(resource: dict) -> str | None:
    version_id = resource.get("meta", {}).get("versionId")
    return f'W/"{version_id}"' if version_id else None


async def withdraw_subject(client: FhirClient, subject_id: str) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    _, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]

    existing_states = subject.get("subjectState", [])
    subject["status"] = "retired"
    subject["subjectState"] = existing_states + [
        {
            "code": {"coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": "off-study"}]},
            "startDate": _today(),
        }
    ]
    updated = await client.update(
        "ResearchSubject", subject_id, subject, if_match=_if_match(subject)
    )
    await revoke_open_workflow(client, patient_id, plan_definition_id)
    return {"id": updated["id"], "subjectState": "withdrawn"}


async def complete_visit(
    client: FhirClient, subject_id: str, action_id: str, transition_choice: str | None
) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    graph, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]

    _, by_action_id = await load_subject_context(client, subject, plan_definition_id)
    encounter = by_action_id.get(action_id)
    if encounter is None:
        raise ValueError(f"No materialized visit found for action {action_id}")

    encounter["status"] = "completed"
    await client.update("Encounter", encounter["id"], encounter, if_match=_if_match(encounter))

    # Re-read subject so we pick up any withdrawal that happened between visits.
    subject = await client.read("ResearchSubject", subject_id)
    context, _ = await load_subject_context(client, subject, plan_definition_id)
    state = resolve_schedule_state(graph, context)

    if len(state.next_steps) == 1:
        node = graph.nodes[state.next_steps[0].action_id]
        await materialize_visit(client, patient_id, plan_definition_id, node)
    elif len(state.next_steps) > 1 and transition_choice is not None:
        chosen = next((s for s in state.next_steps if s.action_id == transition_choice), None)
        if chosen is not None:
            node = graph.nodes[chosen.action_id]
            await materialize_visit(client, patient_id, plan_definition_id, node)

    return schedule_response(state)
