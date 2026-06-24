from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.soa_engine.conditions import SubjectContext
from vulcan_soa.soa_engine.engine import ScheduleState
from vulcan_soa.soa_engine.graph import ProtocolGraph, VisitNode, parse_protocol_graph

ACTION_TAG_SYSTEM = "urn:vulcan-soa:plan-action"


def tag_for(plan_definition_id: str, action_id: str) -> dict:
    return {"system": ACTION_TAG_SYSTEM, "value": f"{plan_definition_id}#{action_id}"}


async def materialize_visit(
    client: FhirClient,
    patient_id: str,
    plan_definition_id: str,
    node: VisitNode,
    status: str = "planned",
) -> dict:
    encounter = {
        "resourceType": "Encounter",
        "status": status,
        "class": [
            {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}]}
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "identifier": [tag_for(plan_definition_id, node.action_id)],
    }
    return await client.create("Encounter", encounter)


async def load_subject_context(
    client: FhirClient, research_subject: dict, plan_definition_id: str
) -> tuple[SubjectContext, dict[str, dict]]:
    state_codes = {
        coding.get("code") for coding in research_subject.get("subjectState", {}).get("coding", [])
    }
    withdrawn = "withdrawn" in state_codes
    patient_id = research_subject["subject"]["reference"].split("/", 1)[1]

    encounters = await client.search(
        "Encounter",
        {"subject": f"Patient/{patient_id}", "identifier": f"{ACTION_TAG_SYSTEM}|"},
    )

    prefix = f"{plan_definition_id}#"
    visited: set[str] = set()
    completed: set[str] = set()
    by_action_id: dict[str, dict] = {}
    for encounter in encounters:
        for identifier in encounter.get("identifier", []):
            if identifier.get("system") != ACTION_TAG_SYSTEM:
                continue
            value = identifier.get("value", "")
            if not value.startswith(prefix):
                continue
            action_id = value[len(prefix):]
            visited.add(action_id)
            by_action_id[action_id] = encounter
            if encounter.get("status") == "finished":
                completed.add(action_id)

    context = SubjectContext(
        withdrawn=withdrawn,
        visited_action_ids=frozenset(visited),
        completed_action_ids=frozenset(completed),
    )
    return context, by_action_id


async def load_protocol_graph(client: FhirClient, study_id: str) -> tuple[ProtocolGraph, str]:
    study = await client.read("ResearchStudy", study_id)
    plan_definition_id = study["protocol"][0]["reference"].split("/", 1)[1]
    plan_definition = await client.read("PlanDefinition", plan_definition_id)
    return parse_protocol_graph(plan_definition), plan_definition_id


async def load_protocol_graph_for_subject(
    client: FhirClient, subject: dict
) -> tuple[ProtocolGraph, str]:
    study_id = subject["study"]["reference"].split("/", 1)[1]
    return await load_protocol_graph(client, study_id)


def schedule_response(state: ScheduleState) -> dict:
    return {
        "completed": sorted(state.completed_action_ids),
        "current": sorted(state.current_action_ids),
        "nextSteps": [
            {"actionId": s.action_id, "title": s.title, "transitionType": s.transition_type}
            for s in state.next_steps
        ],
        "ambiguous": len(state.next_steps) > 1,
    }
