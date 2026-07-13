from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.soa_engine.engine import ScheduleState
from vulcan_soa.soa_engine.graph import ProtocolGraph, parse_protocol_graph

# Records which of a study's protocols a subject was enrolled under.
PLAN_DEFINITION_TAG_SYSTEM = "urn:vulcan-soa:plan-definition"


def assigned_plan_definition_of(subject: dict) -> str | None:
    for entry in subject.get("identifier", []):
        if entry.get("system") == PLAN_DEFINITION_TAG_SYSTEM:
            return entry.get("value")
    return None


async def load_protocol_graph(
    client: FhirClient, study_id: str, plan_definition_id: str | None = None
) -> tuple[ProtocolGraph, str]:
    study = await client.read("ResearchStudy", study_id)
    plan_ids = [
        protocol["reference"].split("/", 1)[1]
        for protocol in study.get("protocol", [])
        if protocol.get("reference")
    ]
    chosen: str = plan_definition_id if plan_definition_id is not None else plan_ids[0]
    if chosen not in plan_ids:
        raise ValueError(f"PlanDefinition '{chosen}' is not a protocol of study {study_id}")
    plan_definition = await client.read("PlanDefinition", chosen)
    return parse_protocol_graph(plan_definition), chosen


async def load_protocol_graph_for_subject(
    client: FhirClient, subject: dict
) -> tuple[ProtocolGraph, str]:
    study_id = subject["study"]["reference"].split("/", 1)[1]
    return await load_protocol_graph(client, study_id, assigned_plan_definition_of(subject))


def schedule_response(
    state: ScheduleState, graph: ProtocolGraph, visits: dict[str, dict] | None = None
) -> dict:
    return {
        "completed": sorted(state.completed_action_ids),
        "current": sorted(state.current_action_ids),
        "nextSteps": [
            {"actionId": s.action_id, "title": s.title, "transitionType": s.transition_type}
            for s in state.next_steps
        ],
        "ambiguous": len(state.next_steps) > 1,
        "visits": visits or {},
        "titles": {action_id: node.title for action_id, node in graph.nodes.items()},
    }
