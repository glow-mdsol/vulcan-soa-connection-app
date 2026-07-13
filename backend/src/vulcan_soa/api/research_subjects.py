from typing import Awaitable

from fastapi import APIRouter, Depends, HTTPException

from vulcan_soa.activity_flow import (
    PhaseError,
    build_request_event_tree,
    complete,
    complete_task,
    context_from_chains,
    expedite,
    list_visit_activities,
    load_chains,
    perform,
    promote,
    respond,
    schedule_visit,
    visit_details,
)
from vulcan_soa.api.deps import get_fhir_client
from vulcan_soa.api.models import (
    AssignIdentifierRequest,
    CompleteVisitRequest,
    RecordMilestoneRequest,
    RespondRequest,
)
from vulcan_soa.enrollment import (
    EnrollmentConflict,
    assign_subject_identifier,
    subject_identifier_of,
)
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph_for_subject, schedule_response
from vulcan_soa.soa_engine.engine import resolve_schedule_state
from vulcan_soa.tracking import (
    delete_enrollment,
    milestones_of,
    record_milestone,
    subject_state_of,
    withdraw_subject,
)

router = APIRouter(prefix="/api/research-subjects")


async def _guarded(coro: Awaitable[dict]) -> dict:
    try:
        return await coro
    except PhaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{subject_id}/schedule")
async def get_schedule(subject_id: str, client: FhirClient = Depends(get_fhir_client)) -> dict:
    subject = await client.read("ResearchSubject", subject_id)
    graph, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]
    chains = await load_chains(client, patient_id, plan_definition_id)
    state = resolve_schedule_state(graph, context_from_chains(subject, chains))
    payload = schedule_response(state, graph, visits=visit_details(chains))
    payload["subjectIdentifier"] = subject_identifier_of(subject)
    payload["subjectStatus"] = subject.get("status")
    payload["subjectState"] = subject_state_of(subject)
    payload["milestones"] = milestones_of(subject)
    payload["studyId"] = subject["study"]["reference"].split("/", 1)[1]
    payload["planDefinitionId"] = plan_definition_id
    return payload


@router.post("/{subject_id}/identifier")
async def assign_identifier_route(
    subject_id: str,
    body: AssignIdentifierRequest,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    try:
        return await assign_subject_identifier(client, subject_id, body.subjectIdentifier)
    except EnrollmentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{subject_id}/milestones")
async def record_milestone_route(
    subject_id: str,
    body: RecordMilestoneRequest,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    return await record_milestone(client, subject_id, body.milestone, body.date, body.display)


@router.get("/{subject_id}/visits/{action_id}/activities")
async def visit_activities_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> list[dict]:
    try:
        return await list_visit_activities(client, subject_id, action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{subject_id}/request-event-tree")
async def request_event_tree_route(
    subject_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await build_request_event_tree(client, subject_id)


@router.post("/{subject_id}/visits/{action_id}/plan")
async def plan_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(promote(client, subject_id, action_id, "plan"))


@router.post("/{subject_id}/visits/{action_id}/order")
async def order_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(promote(client, subject_id, action_id, "order"))


@router.post("/{subject_id}/visits/{action_id}/schedule")
async def schedule_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(schedule_visit(client, subject_id, action_id))


@router.post("/{subject_id}/visits/{action_id}/expedite")
async def expedite_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(expedite(client, subject_id, action_id))


@router.post("/{subject_id}/visits/{action_id}/respond")
async def respond_route(
    subject_id: str,
    action_id: str,
    body: RespondRequest,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    return await _guarded(respond(client, subject_id, action_id, body.participant, body.response))


@router.post("/{subject_id}/visits/{action_id}/perform")
async def perform_route(
    subject_id: str, action_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(perform(client, subject_id, action_id))


@router.post("/{subject_id}/visits/{action_id}/tasks/{task_id}/complete")
async def complete_task_route(
    subject_id: str, action_id: str, task_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await _guarded(complete_task(client, subject_id, action_id, task_id))


@router.post("/{subject_id}/visits/{action_id}/complete")
async def complete_visit_route(
    subject_id: str,
    action_id: str,
    body: CompleteVisitRequest,
    client: FhirClient = Depends(get_fhir_client),
) -> dict:
    return await _guarded(complete(client, subject_id, action_id, body.transitionChoice))


@router.post("/{subject_id}/withdraw")
async def withdraw_route(subject_id: str, client: FhirClient = Depends(get_fhir_client)) -> dict:
    return await withdraw_subject(client, subject_id)


@router.delete("/{subject_id}")
async def delete_enrollment_route(
    subject_id: str, client: FhirClient = Depends(get_fhir_client)
) -> dict:
    return await delete_enrollment(client, subject_id)
