import json
from pathlib import Path

import pytest

from vulcan_soa.soa_engine.graph import parse_protocol_graph

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "plan_definition_uc1.json"

SCREENING_ID = "0700e721-1f12-4998-89b8-6f4e649b62f7"
TREATMENT_DAY1_ID = "a1806239-54f3-4762-af3f-edb9d80d29dc"
DAY7_ID = "349447c3-8ad4-4034-8c31-c3d96dcc5f9a"
DAY15_ID = "d0dd287a-0a87-439d-95cc-8690e7abf0cb"
EOS_ID = "dbc35dee-a5f2-473f-b9b1-bb14b2a1c9ef"
FOLLOWUP_ID = "76fb46ca-2a08-4421-8ce9-b8d412db2fb5"


@pytest.fixture
def plan_definition():
    return json.loads(FIXTURE_PATH.read_text())


def test_parses_all_six_nodes(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    assert set(graph.nodes) == {
        SCREENING_ID, TREATMENT_DAY1_ID, DAY7_ID, DAY15_ID, EOS_ID, FOLLOWUP_ID,
    }


def test_root_is_screening(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    assert graph.root_ids == (SCREENING_ID,)


def test_node_title(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    assert graph.nodes[TREATMENT_DAY1_ID].title == "Treatment Day 1"


def test_treatment_day1_has_two_transitions(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    targets = {t.target_id for t in graph.nodes[TREATMENT_DAY1_ID].transitions}
    assert targets == {DAY7_ID, EOS_ID}


def test_unconditional_transition_has_no_condition(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    to_day7 = next(
        t for t in graph.nodes[TREATMENT_DAY1_ID].transitions if t.target_id == DAY7_ID
    )
    assert to_day7.transition_type == "SS"
    assert to_day7.condition_expression is None


def test_conditional_transition_carries_expression(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    to_eos = next(
        t for t in graph.nodes[TREATMENT_DAY1_ID].transitions if t.target_id == EOS_ID
    )
    assert to_eos.transition_type == "FS"
    assert to_eos.condition_language == "text/x-soa-expressionplain"
    assert to_eos.condition_expression == "{'withdraw':True, 'operation': '=='}"


def test_terminal_node_has_no_transitions(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    assert graph.nodes[FOLLOWUP_ID].transitions == ()


def test_plan_definition_id_recorded(plan_definition):
    graph = parse_protocol_graph(plan_definition)
    assert graph.plan_definition_id == "dynamic-visit-schedule-exit-example-PlanDefinition"
