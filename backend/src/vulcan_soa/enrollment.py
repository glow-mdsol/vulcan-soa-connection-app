import datetime

from vulcan_soa.activity_flow import materialize_proposal
from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph, schedule_response
from vulcan_soa.soa_engine.conditions import SubjectContext
from vulcan_soa.soa_engine.engine import resolve_schedule_state

RESEARCH_SUBJECT_STATE_SYSTEM = "http://terminology.hl7.org/CodeSystem/research-subject-state"


def _today() -> str:
    return datetime.date.today().isoformat()


async def enroll(client: FhirClient, study_id: str, patient_id: str) -> dict:
    graph, plan_definition_id = await load_protocol_graph(client, study_id)

    # R6 ResearchSubject:
    #   - status (1..1) is bound to PublicationStatus: "active" | "draft" | "retired" | "unknown"
    #   - subjectState (0..*) is a BackboneElement array: {code: CodeableConcept, startDate: dateTime}
    subject_resource = {
        "resourceType": "ResearchSubject",
        "status": "active",
        "subjectState": [
            {
                "code": {"coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": "candidate"}]},
                "startDate": _today(),
            }
        ],
        "study": {"reference": f"ResearchStudy/{study_id}"},
        "subject": {"reference": f"Patient/{patient_id}"},
    }
    created = await client.conditional_create(
        "ResearchSubject",
        subject_resource,
        {"study": f"ResearchStudy/{study_id}", "subject": f"Patient/{patient_id}"},
    )

    initial_context = SubjectContext(
        withdrawn=False, visited_action_ids=frozenset(), completed_action_ids=frozenset()
    )
    initial_state = resolve_schedule_state(graph, initial_context)
    for step in initial_state.next_steps:
        node = graph.nodes[step.action_id]
        await materialize_proposal(client, patient_id, plan_definition_id, node)

    materialized_ids = frozenset(step.action_id for step in initial_state.next_steps)
    post_enroll_state = resolve_schedule_state(
        graph,
        SubjectContext(
            withdrawn=False, visited_action_ids=materialized_ids, completed_action_ids=frozenset()
        ),
    )

    visits = {step.action_id: {"phase": "proposed"} for step in initial_state.next_steps}
    return {
        "researchSubjectId": created["id"],
        "schedule": schedule_response(post_enroll_state, visits=visits),
    }
