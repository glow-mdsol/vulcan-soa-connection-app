from vulcan_soa.fhir_client import FhirClient
from vulcan_soa.scheduling import load_protocol_graph, materialize_visit, schedule_response
from vulcan_soa.soa_engine.conditions import SubjectContext
from vulcan_soa.soa_engine.engine import resolve_schedule_state

RESEARCH_SUBJECT_STATE_SYSTEM = "http://terminology.hl7.org/CodeSystem/research-subject-state"


async def enroll(client: FhirClient, study_id: str, patient_id: str) -> dict:
    graph, plan_definition_id = await load_protocol_graph(client, study_id)

    subject_resource = {
        "resourceType": "ResearchSubject",
        "subjectState": {
            "coding": [{"system": RESEARCH_SUBJECT_STATE_SYSTEM, "code": "candidate"}]
        },
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
        await materialize_visit(client, patient_id, plan_definition_id, node)

    materialized_ids = frozenset(step.action_id for step in initial_state.next_steps)
    post_enroll_state = resolve_schedule_state(
        graph,
        SubjectContext(
            withdrawn=False, visited_action_ids=materialized_ids, completed_action_ids=frozenset()
        ),
    )

    return {
        "researchSubjectId": created["id"],
        "schedule": schedule_response(post_enroll_state),
    }
