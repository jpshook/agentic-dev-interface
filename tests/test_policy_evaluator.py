from adi.engine.policy_evaluator import PolicyEvaluator


def test_policy_evaluator_auto_execute() -> None:
    evaluator = PolicyEvaluator()
    decision = evaluator.evaluate(
        risk="low",
        size="small",
        dependencies_satisfied=True,
        touches_restricted_area=False,
    )
    assert decision.action == "auto_execute"


def test_policy_evaluator_require_approval_for_larger_task() -> None:
    evaluator = PolicyEvaluator()
    decision = evaluator.evaluate(
        risk="medium",
        size="medium",
        dependencies_satisfied=True,
        touches_restricted_area=False,
    )
    assert decision.action == "require_approval"


def test_policy_evaluator_require_human_input_for_unsatisfied_dependencies() -> None:
    evaluator = PolicyEvaluator()
    decision = evaluator.evaluate(
        risk="low",
        size="small",
        dependencies_satisfied=False,
        touches_restricted_area=False,
    )
    assert decision.action == "require_human_input"


def test_policy_evaluator_deny_restricted_area() -> None:
    evaluator = PolicyEvaluator()
    decision = evaluator.evaluate(
        risk="low",
        size="small",
        dependencies_satisfied=True,
        touches_restricted_area=True,
    )
    assert decision.action == "deny"
