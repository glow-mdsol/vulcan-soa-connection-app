"""CPG activity-flow lifecycle: proposal → plan → order → schedule/book → perform → complete.

Each phase of a visit is a distinct FHIR resource linked by basedOn, per the CPG
activity flow (https://hl7.org/fhir/uv/cpg/activityflow.html). Chain membership is
tracked by the shared action-tag identifier on every resource in the chain.
"""

import datetime
from dataclasses import dataclass, field

from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import (
    load_protocol_graph,
    load_protocol_graph_for_subject,
    schedule_response,
)
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
        # An encounter in flight stays completable even after withdrawal — the
        # visit happened and must remain documentable.
        if self.encounter is not None:
            return "performing"
        # Terminal (post-withdrawal) states: a cancelled appointment or a revoked
        # visit-level request means the workflow was torn down before the visit
        # took place. Report "revoked" so the UI shows no actionable gates and
        # respond() can't book it.
        if self.appointment is not None and self.appointment.get("status") == "cancelled":
            return "revoked"
        if any(request.get("status") == "revoked" for request in self.requests.values()):
            return "revoked"
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


def _resource_id_from_uri(uri: str, resource_type: str) -> str | None:
    # Handles both relative ("PlanDefinition/x") and canonical
    # ("http://example.org/.../PlanDefinition/x") references.
    marker = f"{resource_type}/"
    if marker not in uri:
        return None
    return uri.rsplit(marker, 1)[1]


def _observation_definition_id(reference) -> str | None:
    uri = reference if isinstance(reference, str) else reference.get("reference", "")
    return _resource_id_from_uri(uri, "ObservationDefinition")


async def _read_observation_tree(
    client: FhirClient, od_id: str, seen: set[str]
) -> dict | None:
    # `seen` guards against hasMember reference cycles.
    if od_id in seen:
        return None
    seen.add(od_id)

    od = await client.read("ObservationDefinition", od_id)
    code = od.get("code", {})
    coding = (code.get("coding") or [{}])[0]

    members = []
    for reference in od.get("hasMember", []):
        member_id = _observation_definition_id(reference)
        if member_id is None:
            continue
        member = await _read_observation_tree(client, member_id, seen)
        if member is not None:
            members.append(member)

    return {
        "id": od["id"],
        "display": code.get("text")
        or coding.get("display")
        or od.get("title")
        or coding.get("code")
        or od["id"],
        "members": members,
    }


async def _expected_observations(client: FhirClient, definition: dict) -> list[dict]:
    references = definition.get("observationResultRequirement") or definition.get(
        "observationRequirement"
    ) or []
    observations = []
    seen: set[str] = set()
    for reference in references:
        od_id = _observation_definition_id(reference)
        if od_id is None:
            continue
        observation = await _read_observation_tree(client, od_id, seen)
        if observation is not None:
            observations.append(observation)
    return observations


async def _activity_node(client: FhirClient, action: dict) -> dict | None:
    uri = action.get("definitionUri") or action.get("definitionCanonical") or ""
    questionnaire_id = _resource_id_from_uri(uri, "Questionnaire")
    activity_definition_id = _resource_id_from_uri(uri, "ActivityDefinition")
    if questionnaire_id is not None:
        return {
            "id": questionnaire_id,
            "title": action.get("title") or questionnaire_id,
            "type": "Questionnaire",
            "observations": [],
        }
    if activity_definition_id is not None:
        definition = await client.read("ActivityDefinition", activity_definition_id)
        return {
            "id": definition["id"],
            "title": action.get("title") or definition.get("title") or definition["id"],
            "type": "ActivityDefinition",
            "observations": await _expected_observations(client, definition),
        }
    return None


async def list_visit_activities(
    client: FhirClient, subject_id: str, action_id: str
) -> list[dict]:
    subject = await client.read("ResearchSubject", subject_id)
    graph, _ = await load_protocol_graph_for_subject(client, subject)
    node = graph.nodes.get(action_id)
    if node is None:
        raise ValueError(f"Unknown visit action {action_id}")

    visit_pd_id = _resource_id_from_uri(node.definition_uri or "", "PlanDefinition")
    if visit_pd_id is None:
        return []
    visit_pd = await client.read("PlanDefinition", visit_pd_id)

    activities = []
    for action in visit_pd.get("action", []):
        activity = await _activity_node(client, action)
        if activity is not None:
            activities.append(activity)
    return activities


def _observation_tree_node(observation: dict) -> dict:
    return {
        "id": observation["id"],
        "type": "ObservationDefinition",
        "label": observation["display"],
        "children": [_observation_tree_node(member) for member in observation["members"]],
    }


async def _visit_tree_node(client: FhirClient, action: dict) -> dict:
    action_id = action.get("id", "")
    uri = action.get("definitionUri") or action.get("definitionCanonical") or ""
    visit_pd_id = _resource_id_from_uri(uri, "PlanDefinition")

    children = []
    if visit_pd_id is not None:
        visit_pd = await client.read("PlanDefinition", visit_pd_id)
        for sub_action in visit_pd.get("action", []):
            activity = await _activity_node(client, sub_action)
            if activity is None:
                continue
            children.append(
                {
                    "id": activity["id"],
                    "type": activity["type"],
                    "label": activity["title"],
                    "children": [
                        _observation_tree_node(obs) for obs in activity["observations"]
                    ],
                }
            )

    return {
        "id": action_id,
        "type": "PlanDefinition",
        "label": action.get("title") or action_id,
        "children": children,
    }


async def build_protocol_tree(
    client: FhirClient, study_id: str, plan_definition_id: str | None = None
) -> dict:
    study = await client.read("ResearchStudy", study_id)
    _, plan_definition_id = await load_protocol_graph(client, study_id, plan_definition_id)
    root_plan_definition = await client.read("PlanDefinition", plan_definition_id)

    visit_children = [
        await _visit_tree_node(client, action)
        for action in root_plan_definition.get("action", [])
    ]

    return {
        "id": study_id,
        "type": "ResearchStudy",
        "label": study.get("title", study_id),
        "children": [
            {
                "id": plan_definition_id,
                "type": "PlanDefinition",
                "label": root_plan_definition.get("title", plan_definition_id),
                "children": visit_children,
            }
        ],
    }


_INTENT_ORDER = ("proposal", "plan", "order")


def _request_chain_node(
    by_intent: dict[str, dict], proposal_children: list[dict], tail_children: list[dict]
) -> dict | None:
    """Nest the proposal -> plan -> order chain actually materialized so far.

    `proposal_children` (e.g. an activity's own chain) attach to the proposal,
    matching where the CPG flow really creates them (basedOn the proposal);
    `tail_children` (e.g. Appointment) attach to the most-advanced intent
    present, since that's the request that spawned them.
    """
    present = [intent for intent in _INTENT_ORDER if intent in by_intent]
    if not present:
        return None

    nodes = [
        {
            "id": by_intent[intent]["id"],
            "type": "ServiceRequest",
            "label": f"{_request_text(by_intent[intent])} — {intent} · {by_intent[intent].get('status', '')}",
            "children": [],
        }
        for intent in present
    ]
    nodes[0]["children"] = list(proposal_children)
    for i in range(len(nodes) - 1):
        nodes[i]["children"].append(nodes[i + 1])
    nodes[-1]["children"].extend(tail_children)
    return nodes[0]


def _appointment_node(appointment: dict, children: list[dict]) -> dict:
    return {
        "id": appointment["id"],
        "type": "Appointment",
        "label": f"Appointment — {appointment.get('status', '')}",
        "children": children,
    }


def _encounter_node(encounter: dict) -> dict:
    return {
        "id": encounter["id"],
        "type": "Encounter",
        "label": f"Encounter — {encounter.get('status', '')}",
        "children": [],
    }


def _task_activity_id(task: dict, plan_definition_id: str) -> str | None:
    parsed = parse_tag(tag_value(task) or "", plan_definition_id)
    return parsed[1] if parsed else None


async def _task_event_node(client: FhirClient, task: dict) -> dict:
    children = []
    for output in task.get("output", []):
        reference = output.get("valueReference", {}).get("reference", "")
        procedure_id = _resource_id_from_uri(reference, "Procedure")
        if procedure_id is None:
            continue
        procedure = await client.read("Procedure", procedure_id)
        code = procedure.get("code", {})
        coding = (code.get("coding") or [{}])[0]
        label = code.get("text") or coding.get("display") or coding.get("code") or procedure["id"]
        children.append(
            {
                "id": procedure["id"],
                "type": "Procedure",
                "label": f"{label} — {procedure.get('status', '')}",
                "children": [],
            }
        )
    return {
        "id": task["id"],
        "type": "Task",
        "label": f"{task.get('description') or 'Task'} — {task.get('status', '')}",
        "children": children,
    }


async def _visit_event_node(
    client: FhirClient, chain: VisitChain, plan_definition_id: str
) -> dict | None:
    tail_children = []
    if chain.appointment is not None:
        appointment_children = (
            [_encounter_node(chain.encounter)] if chain.encounter is not None else []
        )
        tail_children = [_appointment_node(chain.appointment, appointment_children)]

    activity_nodes = []
    for activity_id, by_intent in chain.activities.items():
        matching_tasks = [
            task for task in chain.tasks if _task_activity_id(task, plan_definition_id) == activity_id
        ]
        task_nodes = [await _task_event_node(client, task) for task in matching_tasks]
        activity_node = _request_chain_node(by_intent, [], task_nodes)
        if activity_node is not None:
            activity_nodes.append(activity_node)

    return _request_chain_node(chain.requests, activity_nodes, tail_children)


async def build_request_event_tree(client: FhirClient, subject_id: str) -> dict:
    """The instance-level counterpart to `build_protocol_tree`: what has actually
    been materialized for this subject so far, following the real basedOn/output
    lineage from each visit's proposal through to Appointment/Encounter/Task/Procedure.
    """
    workspace = await _load_workspace(client, subject_id)

    visit_nodes = []
    for action_id in workspace.graph.nodes:
        chain = workspace.chains.get(action_id)
        if chain is None:
            continue
        visit_node = await _visit_event_node(client, chain, workspace.plan_definition_id)
        if visit_node is not None:
            visit_nodes.append(visit_node)

    subject_identifier = next(
        (
            entry.get("value")
            for entry in workspace.subject.get("identifier", [])
            if entry.get("system") == "urn:vulcan-soa:subject-id"
        ),
        None,
    )
    return {
        "id": subject_id,
        "type": "ResearchSubject",
        "label": subject_identifier or subject_id,
        "children": visit_nodes,
    }


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
    return schedule_response(state, workspace.graph, visits=visit_details(chains))


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


_EXPEDITE_STEPS = {
    "proposed": ("plan", "order", "schedule"),
    "planned": ("order", "schedule"),
    "ordered": ("schedule",),
}


async def expedite(client: FhirClient, subject_id: str, action_id: str) -> dict:
    """Walk a visit through its remaining gates to `scheduled` in one call.

    Composes the single-step gates, so every intermediate ServiceRequest is
    still created and completed; a mid-batch failure leaves the visit in a
    valid intermediate phase recoverable via the individual gate buttons.
    """
    workspace = await _load_workspace(client, subject_id)
    chain = workspace.chains.get(action_id)
    if chain is None:
        raise ValueError(f"No materialized visit found for action {action_id}")
    steps = _EXPEDITE_STEPS.get(chain.phase)
    if steps is None:
        raise PhaseError(
            f"visit {action_id} is in phase '{chain.phase}', "
            f"expected one of {sorted(_EXPEDITE_STEPS)}"
        )

    payload: dict = {}
    for step in steps:
        if step == "schedule":
            payload = await schedule_visit(client, subject_id, action_id)
        else:
            payload = await promote(client, subject_id, action_id, step)
    return payload


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
    return schedule_response(final_state, workspace.graph, visits=visit_details(final_chains))


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
