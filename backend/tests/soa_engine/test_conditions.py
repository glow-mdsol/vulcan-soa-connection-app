from vulcan_soa.soa_engine.conditions import SubjectContext, evaluate_condition


def make_context(withdrawn=False):
    return SubjectContext(
        withdrawn=withdrawn, visited_action_ids=frozenset(), completed_action_ids=frozenset()
    )


def test_withdraw_true_matches_withdrawn_subject():
    context = make_context(withdrawn=True)
    assert evaluate_condition(
        "text/x-soa-expressionplain", "{'withdraw':True, 'operation': '=='}", context
    ) is True


def test_withdraw_true_does_not_match_active_subject():
    context = make_context(withdrawn=False)
    assert evaluate_condition(
        "text/x-soa-expressionplain", "{'withdraw':True, 'operation': '=='}", context
    ) is False


def test_withdrawn_key_synonym_is_supported():
    context = make_context(withdrawn=True)
    assert evaluate_condition("text/x-soa-expressionplain", "{'withdrawn':true}", context) is True


def test_operation_defaults_to_equals():
    context = make_context(withdrawn=True)
    assert evaluate_condition("text/x-soa-expressionplain", "{'withdraw':True}", context) is True


def test_not_equals_operation():
    context = make_context(withdrawn=True)
    assert evaluate_condition(
        "text/x-soa-expressionplain", "{'withdraw':True, 'operation': '!='}", context
    ) is False


def test_unsupported_language_fails_closed():
    context = make_context(withdrawn=True)
    assert evaluate_condition("text/fhirpath", "anything", context) is False


def test_unrecognized_key_fails_closed():
    context = make_context(withdrawn=True)
    assert evaluate_condition("text/x-soa-expressionplain", "{'exists':['V1']}", context) is False


def test_malformed_expression_fails_closed():
    context = make_context(withdrawn=True)
    assert evaluate_condition("text/x-soa-expressionplain", "{not valid python", context) is False
