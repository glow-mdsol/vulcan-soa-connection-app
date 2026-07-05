from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.soa_engine.engine import ScheduleState
from vulcan_soa.soa_engine.graph import ProtocolGraph, parse_protocol_graph


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


def schedule_response(state: ScheduleState, visits: dict[str, dict] | None = None) -> dict:
    return {
        "completed": sorted(state.completed_action_ids),
        "current": sorted(state.current_action_ids),
        "nextSteps": [
            {"actionId": s.action_id, "title": s.title, "transitionType": s.transition_type}
            for s in state.next_steps
        ],
        "ambiguous": len(state.next_steps) > 1,
        "visits": visits or {},
    }
