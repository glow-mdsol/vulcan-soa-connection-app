from fastapi import APIRouter, Depends

from vulcan_soa.activity_flow import complete, context_from_chains, load_chains, visit_details
from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.models import CompleteVisitRequest
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph_for_subject, schedule_response
from vulcan_soa.soa_engine.engine import resolve_schedule_state
from vulcan_soa.tracking import withdraw_subject

router = APIRouter(prefix="/api/research-subjects")


@router.get("/{subject_id}/schedule")
async def get_schedule(subject_id: str, client: FhirClient = Depends(get_fhir_client)) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    graph, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]
    chains = await load_chains(client, patient_id, plan_definition_id)
    state = resolve_schedule_state(graph, context_from_chains(subject, chains))
    return schedule_response(state, visits=visit_details(chains))


@router.post("/{subject_id}/visits/{action_id}/complete")
async def complete_visit_route(
    subject_id: str,
    action_id: str,
    body: CompleteVisitRequest,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    return await complete(client, subject_id, action_id, body.transitionChoice)


@router.post("/{subject_id}/withdraw")
async def withdraw_route(subject_id: str, client: FhirClient = Depends(get_fhir_client)) -> dict:
    return await withdraw_subject(client, subject_id)
