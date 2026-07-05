"""CPG activity-flow lifecycle: proposal → plan → order → schedule/book → perform → complete.

Each phase of a visit is a distinct FHIR resource linked by basedOn, per the CPG
activity flow (https://hl7.org/fhir/uv/cpg/activityflow.html). Chain membership is
tracked by the shared action-tag identifier on every resource in the chain.
"""

import datetime
from dataclasses import dataclass, field

from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph_for_subject, schedule_response
from vulcan_soa.soa_engine.conditions import SubjectContext
from vulcan_soa.soa_engine.engine import resolve_schedule_state
from vulcan_soa.soa_engine.graph import ProtocolGraph, VisitNode

ACTION_TAG_SYSTEM = "urn:vulcan-soa:plan-action"
GROUP_ID_SYSTEM = "urn:vulcan-soa:promotion"
SITE_PRACTITIONER_ID = "site-coordinator-demo"

_PARTICIPANT_ROLES = {"Patient": "patient", "Practitioner": "site"}


class PhaseError(Exception):
    """A lifecycle gate was attempted from the wrong phase."""


def visit_tag(plan_definition_id: str, action_id: str) -> dict:
    return {"system": ACTION_TAG_SYSTEM, "value": f"{plan_definition_id}#{action_id}"}


def activity_tag(plan_definition_id: str, action_id: str, activity_id: str) -> dict:
    return {"system": ACTION_TAG_SYSTEM, "value": f"{plan_definition_id}#{action_id}#{activity_id}"}


def group_identifier(plan_definition_id: str, action_id: str, intent: str) -> dict:
    return {"system": GROUP_ID_SYSTEM, "value": f"{plan_definition_id}#{action_id}:{intent}"}


def parse_tag(value: str, plan_definition_id: str) -> tuple[str, str | None] | None:
    prefix = f"{plan_definition_id}#"
    if not value.startswith(prefix):
        return None
    action_id, _, activity_id = value[len(prefix):].partition("#")
    return action_id, activity_id or None


def tag_value(resource: dict) -> str | None:
    for identifier in resource.get("identifier", []):
        if identifier.get("system") == ACTION_TAG_SYSTEM:
            return identifier.get("value")
    return None


def if_match_header(resource: dict) -> str | None:
    version_id = resource.get("meta", {}).get("versionId")
    return f'W/"{version_id}"' if version_id else None


@dataclass
class VisitChain:
    action_id: str
    requests: dict[str, dict] = field(default_factory=dict)
    activities: dict[str, dict[str, dict]] = field(default_factory=dict)
    appointment: dict | None = None
    encounter: dict | None = None
    tasks: list[dict] = field(default_factory=list)

    @property
    def phase(self) -> str:
        if self.encounter is not None and self.encounter.get("status") == "completed":
            return "completed"
        # Terminal (post-withdrawal) states: a cancelled appointment or a revoked
        # visit-level request means the workflow was torn down. Report "revoked"
        # so the UI shows no actionable gates and respond() can't book it.
        if self.appointment is not None and self.appointment.get("status") == "cancelled":
            return "revoked"
        if any(request.get("status") == "revoked" for request in self.requests.values()):
            return "revoked"
        if self.encounter is not None:
            return "performing"
        if self.appointment is not None and self.appointment.get("status") == "booked":
            return "booked"
        if self.appointment is not None:
            return "scheduled"
        if "order" in self.requests:
            return "ordered"
        if "plan" in self.requests:
            return "planned"
        return "proposed"


def context_from_chains(research_subject: dict, chains: dict[str, VisitChain]) -> SubjectContext:
    return SubjectContext(
        withdrawn=research_subject.get("status") == "retired",
        visited_action_ids=frozenset(chains),
        completed_action_ids=frozenset(
            action_id for action_id, chain in chains.items() if chain.phase == "completed"
        ),
    )


def visit_details(chains: dict[str, VisitChain]) -> dict[str, dict]:
    details: dict[str, dict] = {}
    for action_id, chain in chains.items():
        detail: dict = {"phase": chain.phase}
        if chain.appointment is not None:
            detail["participants"] = [
                {
                    "role": _PARTICIPANT_ROLES.get(
                        participant.get("actor", {}).get("reference", "").split("/", 1)[0], "other"
                    ),
                    "status": participant.get("status", "needs-action"),
                }
                for participant in chain.appointment.get("participant", [])
            ]
        if chain.tasks:
            detail["tasks"] = [
                {
                    "id": task["id"],
                    "description": task.get("description", ""),
                    "status": task.get("status", ""),
                }
                for task in chain.tasks
            ]
        details[action_id] = detail
    return details


async def load_chains(
    client: FhirClient, patient_id: str, plan_definition_id: str
) -> dict[str, VisitChain]:
    chains: dict[str, VisitChain] = {}
    patient_reference = f"Patient/{patient_id}"

    def chain_for(action_id: str) -> VisitChain:
        if action_id not in chains:
            chains[action_id] = VisitChain(action_id=action_id)
        return chains[action_id]

    def parsed_tag(resource: dict) -> tuple[str, str | None] | None:
        return parse_tag(tag_value(resource) or "", plan_definition_id)

    tagged = {"identifier": f"{ACTION_TAG_SYSTEM}|"}

    for request in await client.search("ServiceRequest", {"subject": patient_reference, **tagged}):
        parsed = parsed_tag(request)
        if parsed is None:
            continue
        action_id, activity_id = parsed
        chain = chain_for(action_id)
        if activity_id is None:
            chain.requests[request.get("intent", "")] = request
        else:
            chain.activities.setdefault(activity_id, {})[request.get("intent", "")] = request

    # Appointment and Task have no subject search param on all servers; filter client-side.
    for appointment in await client.search("Appointment", tagged):
        parsed = parsed_tag(appointment)
        if parsed is None:
            continue
        actors = [p.get("actor", {}).get("reference") for p in appointment.get("participant", [])]
        if patient_reference not in actors:
            continue
        chain_for(parsed[0]).appointment = appointment

    for encounter in await client.search("Encounter", {"subject": patient_reference, **tagged}):
        parsed = parsed_tag(encounter)
        if parsed is None:
            continue
        chain_for(parsed[0]).encounter = encounter

    for task in await client.search("Task", tagged):
        parsed = parsed_tag(task)
        if parsed is None:
            continue
        if task.get("for", {}).get("reference") != patient_reference:
            continue
        chain_for(parsed[0]).tasks.append(task)

    return chains


async def materialize_proposal(
    client: FhirClient, patient_id: str, plan_definition_id: str, node: VisitNode
) -> dict:
    group = group_identifier(plan_definition_id, node.action_id, "proposal")
    visit_request = {
        "resourceType": "ServiceRequest",
        "status": "active",
        "intent": "proposal",
        "subject": {"reference": f"Patient/{patient_id}"},
        "identifier": [visit_tag(plan_definition_id, node.action_id)],
        "requisition": group,
        "code": {"concept": {"text": node.title}},
    }
    if node.definition_uri:
        visit_request["instantiatesUri"] = [node.definition_uri]
    created_visit = await client.create("ServiceRequest", visit_request)

    for definition in await _load_activity_definitions(client, node):
        activity_request = {
            "resourceType": "ServiceRequest",
            "status": "active",
            "intent": "proposal",
            "subject": {"reference": f"Patient/{patient_id}"},
            "identifier": [activity_tag(plan_definition_id, node.action_id, definition["id"])],
            "requisition": group,
            "instantiatesUri": [f"ActivityDefinition/{definition['id']}"],
            "basedOn": [{"reference": f"ServiceRequest/{created_visit['id']}"}],
            "code": {"concept": definition.get("code") or {"text": definition.get("title", definition["id"])}},
        }
        await client.create("ServiceRequest", activity_request)
    return created_visit


async def _load_activity_definitions(client: FhirClient, node: VisitNode) -> list[dict]:
    if not node.definition_uri or not node.definition_uri.startswith("PlanDefinition/"):
        return []
    visit_pd = await client.read("PlanDefinition", node.definition_uri.split("/", 1)[1])
    definitions = []
    for action in visit_pd.get("action", []):
        uri = action.get("definitionUri", "")
        # Only ActivityDefinition-backed activities; Questionnaire refs are out of scope.
        if uri.startswith("ActivityDefinition/"):
            definitions.append(await client.read("ActivityDefinition", uri.split("/", 1)[1]))
    return definitions


_PROMOTIONS = {"plan": ("proposed", "proposal"), "order": ("planned", "plan")}


@dataclass
class _SubjectWorkspace:
    subject: dict
    graph: ProtocolGraph
    plan_definition_id: str
    patient_id: str
    chains: dict[str, VisitChain]


async def _load_workspace(client: FhirClient, subject_id: str) -> _SubjectWorkspace:
    subject = await client.read("ResearchSubject", subject_id)
    graph, plan_definition_id = await load_protocol_graph_for_subject(client, subject)
    patient_id = subject["subject"]["reference"].split("/", 1)[1]
    chains = await load_chains(client, patient_id, plan_definition_id)
    return _SubjectWorkspace(subject, graph, plan_definition_id, patient_id, chains)


def _require_phase(chain: VisitChain | None, action_id: str, expected: str) -> VisitChain:
    if chain is None:
        raise ValueError(f"No materialized visit found for action {action_id}")
    if chain.phase != expected:
        raise PhaseError(f"visit {action_id} is in phase '{chain.phase}', expected '{expected}'")
    return chain


async def _complete_request(client: FhirClient, request: dict) -> None:
    request["status"] = "completed"
    await client.update("ServiceRequest", request["id"], request, if_match=if_match_header(request))


async def schedule_payload(client: FhirClient, workspace: _SubjectWorkspace) -> dict:
    chains = await load_chains(client, workspace.patient_id, workspace.plan_definition_id)
    state = resolve_schedule_state(workspace.graph, context_from_chains(workspace.subject, chains))
    return schedule_response(state, visits=visit_details(chains))


def _next_request(previous: dict, intent: str, group: dict, based_on: list[dict]) -> dict:
    request = {
        "resourceType": "ServiceRequest",
        "status": "active",
        "intent": intent,
        "subject": previous["subject"],
        "identifier": previous["identifier"],
        "requisition": group,
        "basedOn": [{"reference": f"ServiceRequest/{r['id']}"} for r in based_on],
        "code": previous.get("code"),
    }
    if previous.get("instantiatesUri"):
        request["instantiatesUri"] = previous["instantiatesUri"]
    return request


async def promote(client: FhirClient, subject_id: str, action_id: str, to_intent: str) -> dict:
    required_phase, previous_intent = _PROMOTIONS[to_intent]
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, required_phase)

    group = group_identifier(workspace.plan_definition_id, action_id, to_intent)
    previous_visit = chain.requests[previous_intent]
    created_visit = await client.create(
        "ServiceRequest", _next_request(previous_visit, to_intent, group, based_on=[previous_visit])
    )
    await _complete_request(client, previous_visit)

    for by_intent in chain.activities.values():
        previous_activity = by_intent.get(previous_intent)
        if previous_activity is None:
            continue
        await client.create(
            "ServiceRequest",
            _next_request(previous_activity, to_intent, group, based_on=[previous_activity, created_visit]),
        )
        await _complete_request(client, previous_activity)

    return await schedule_payload(client, workspace)


def _default_appointment_window() -> tuple[str, str]:
    # Placeholder slot: no real calendar/site-availability integration exists yet.
    # R6 Appointment invariant app-3 requires start/end once status leaves
    # proposed/cancelled/waitlist, so a window is stamped on at creation time.
    start = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    end = start + datetime.timedelta(hours=1)
    return start.isoformat(), end.isoformat()


async def schedule_visit(client: FhirClient, subject_id: str, action_id: str) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "ordered")
    order = chain.requests["order"]
    start, end = _default_appointment_window()
    await client.create(
        "Appointment",
        {
            "resourceType": "Appointment",
            "status": "proposed",
            "identifier": [visit_tag(workspace.plan_definition_id, action_id)],
            "basedOn": [{"reference": f"ServiceRequest/{order['id']}"}],
            "start": start,
            "end": end,
            "participant": [
                {"actor": {"reference": f"Patient/{workspace.patient_id}"}, "status": "needs-action"},
                {"actor": {"reference": f"Practitioner/{SITE_PRACTITIONER_ID}"}, "status": "needs-action"},
            ],
        },
    )
    return await schedule_payload(client, workspace)


async def respond(
    client: FhirClient, subject_id: str, action_id: str, participant: str, response: str
) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "scheduled")
    appointment = chain.appointment
    actor_reference = (
        f"Patient/{workspace.patient_id}"
        if participant == "patient"
        else f"Practitioner/{SITE_PRACTITIONER_ID}"
    )
    await client.create(
        "AppointmentResponse",
        {
            "resourceType": "AppointmentResponse",
            "appointment": {"reference": f"Appointment/{appointment['id']}"},
            "actor": {"reference": actor_reference},
            "participantStatus": response,
        },
    )
    for slot in appointment.get("participant", []):
        if slot.get("actor", {}).get("reference") == actor_reference:
            slot["status"] = response
    if all(slot.get("status") == "accepted" for slot in appointment.get("participant", [])):
        appointment["status"] = "booked"
    await client.update(
        "Appointment", appointment["id"], appointment, if_match=if_match_header(appointment)
    )
    return await schedule_payload(client, workspace)


def _request_text(request: dict) -> str:
    concept = request.get("code", {}).get("concept", {})
    if concept.get("text"):
        return concept["text"]
    for coding in concept.get("coding", []):
        if coding.get("display"):
            return coding["display"]
    return tag_value(request) or ""


async def perform(client: FhirClient, subject_id: str, action_id: str) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "booked")
    order = chain.requests["order"]
    created_encounter = await client.create(
        "Encounter",
        {
            "resourceType": "Encounter",
            "status": "in-progress",
            "class": [
                {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"}]}
            ],
            "subject": {"reference": f"Patient/{workspace.patient_id}"},
            "appointment": [{"reference": f"Appointment/{chain.appointment['id']}"}],
            "basedOn": [{"reference": f"ServiceRequest/{order['id']}"}],
            "identifier": [visit_tag(workspace.plan_definition_id, action_id)],
        },
    )

    for activity_id, by_intent in chain.activities.items():
        activity_order = by_intent.get("order")
        if activity_order is None:
            continue
        await client.create(
            "Task",
            {
                "resourceType": "Task",
                "status": "ready",
                "intent": "order",
                "identifier": [activity_tag(workspace.plan_definition_id, action_id, activity_id)],
                "basedOn": [{"reference": f"ServiceRequest/{activity_order['id']}"}],
                "focus": {"reference": f"ServiceRequest/{activity_order['id']}"},
                "for": {"reference": f"Patient/{workspace.patient_id}"},
                "encounter": {"reference": f"Encounter/{created_encounter['id']}"},
                "description": _request_text(activity_order),
            },
        )
    return await schedule_payload(client, workspace)


def _activity_order_for_task(chain: VisitChain, task: dict) -> dict:
    value = tag_value(task) or ""
    activity_id = value.rpartition("#")[2]
    return chain.activities.get(activity_id, {}).get("order", {})


async def _complete_task_resource(client: FhirClient, patient_id: str, chain: VisitChain, task: dict) -> None:
    if task.get("status") in ("completed", "cancelled"):
        return
    order = _activity_order_for_task(chain, task)
    procedure = {
        "resourceType": "Procedure",
        "status": "completed",
        "code": order.get("code", {}).get("concept") or {"text": task.get("description", "")},
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": task.get("encounter"),
        "identifier": task.get("identifier", []),
    }
    if order.get("id"):
        procedure["basedOn"] = [{"reference": f"ServiceRequest/{order['id']}"}]
    created = await client.create("Procedure", procedure)
    task["status"] = "completed"
    task["output"] = [
        {"type": {"text": "procedure"}, "valueReference": {"reference": f"Procedure/{created['id']}"}}
    ]
    await client.update("Task", task["id"], task, if_match=if_match_header(task))


async def complete_task(client: FhirClient, subject_id: str, action_id: str, task_id: str) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = _require_phase(workspace.chains.get(action_id), action_id, "performing")
    task = next((t for t in chain.tasks if t["id"] == task_id), None)
    if task is None:
        raise ValueError(f"No task {task_id} found for action {action_id}")
    await _complete_task_resource(client, workspace.patient_id, chain, task)
    return await schedule_payload(client, workspace)


def _all_requests(chain: VisitChain) -> list[dict]:
    activity_requests = [
        request for by_intent in chain.activities.values() for request in by_intent.values()
    ]
    return [*chain.requests.values(), *activity_requests]


async def complete(
    client: FhirClient, subject_id: str, action_id: str, transition_choice: str | None
) -> dict:
    workspace = await _load_workspace(client, subject_id)
    chain = workspace.chains.get(action_id)

    # Re-entry: the frontend's ambiguous flow calls complete() a second time with
    # the chosen branch. The first call already completed the Encounter (phase is
    # now "completed"), so skip the sweep/request/encounter mutation and go
    # straight to recording the chosen branch.
    reentry = chain is not None and chain.phase == "completed" and transition_choice is not None
    if not reentry:
        if chain is not None and chain.phase == "completed" and transition_choice is None:
            raise PhaseError(f"visit {action_id} is in phase 'completed', expected 'performing'")
        chain = _require_phase(chain, action_id, "performing")

        for task in chain.tasks:
            await _complete_task_resource(client, workspace.patient_id, chain, task)
        for request in _all_requests(chain):
            if request.get("status") == "active":
                await _complete_request(client, request)

        encounter = chain.encounter
        encounter["status"] = "completed"
        await client.update(
            "Encounter", encounter["id"], encounter, if_match=if_match_header(encounter)
        )

    # Re-read subject so we pick up any withdrawal that happened between visits.
    subject = await client.read("ResearchSubject", subject_id)
    chains = await load_chains(client, workspace.patient_id, workspace.plan_definition_id)
    state = resolve_schedule_state(workspace.graph, context_from_chains(subject, chains))

    def unmaterialized(step_action_id: str) -> bool:
        return step_action_id not in chains

    if len(state.next_steps) == 1:
        node = workspace.graph.nodes[state.next_steps[0].action_id]
        if unmaterialized(node.action_id):
            await materialize_proposal(
                client, workspace.patient_id, workspace.plan_definition_id, node
            )
    elif len(state.next_steps) > 1 and transition_choice is not None:
        chosen = next((s for s in state.next_steps if s.action_id == transition_choice), None)
        if chosen is not None and unmaterialized(chosen.action_id):
            node = workspace.graph.nodes[chosen.action_id]
            await materialize_proposal(
                client, workspace.patient_id, workspace.plan_definition_id, node
            )

    # Recompute the returned state from the FINAL chains so a freshly materialized
    # proposal is reflected in `current` (otherwise the UI dead-ends).
    final_chains = await load_chains(client, workspace.patient_id, workspace.plan_definition_id)
    final_state = resolve_schedule_state(
        workspace.graph, context_from_chains(subject, final_chains)
    )
    return schedule_response(final_state, visits=visit_details(final_chains))


async def revoke_open_workflow(client: FhirClient, patient_id: str, plan_definition_id: str) -> None:
    chains = await load_chains(client, patient_id, plan_definition_id)
    for chain in chains.values():
        for request in _all_requests(chain):
            if request.get("status") == "active":
                request["status"] = "revoked"
                await client.update(
                    "ServiceRequest", request["id"], request, if_match=if_match_header(request)
                )
        if chain.appointment is not None and chain.appointment.get("status") in ("proposed", "booked"):
            chain.appointment["status"] = "cancelled"
            await client.update(
                "Appointment",
                chain.appointment["id"],
                chain.appointment,
                if_match=if_match_header(chain.appointment),
            )
        for task in chain.tasks:
            if task.get("status") in ("ready", "in-progress"):
                task["status"] = "cancelled"
                await client.update("Task", task["id"], task, if_match=if_match_header(task))
