"""End-to-end tests for the LangGraph orchestrator: the plan -> implement -> review loop, the
human-in-the-loop clarification interrupt, bounded per-step retries, and the hard step-budget
circuit breaker.

Uses fake Planner/Coder/Tool agents (queued canned AgentMessages) rather than the real agents --
each agent's own internals already have dedicated tests in their own phases. These tests are
about the orchestrator's routing and state logic: does it advance, retry, escalate, or pause for
a human at the right times.
"""

from multiagent.contracts.messages import PlanStep
from multiagent.orchestrator.orchestrator import Orchestrator  # noqa: F401
from tests.orchestrator.fakes import (
    FakeCoderAgent,
    FakePlannerAgent,
    FakeToolAgent,
    coder_error,
    coder_ok,
    make_orchestrator,
    plan_error,
    plan_needs_clarification,
    plan_ok,
    review,
    tool_error,
    tool_ok,
)


def test_happy_path_single_step_reaches_done():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[plan_ok([step])], review_responses=[review(1, approved=True)]
    )
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool)

    result = orchestrator.run(task_id="t1", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(tool.commit_calls) == 1
    assert len(tool.pr_calls) == 1


def test_clarification_interrupt_then_resume_produces_a_plan():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[plan_needs_clarification(["which framework?"]), plan_ok([step])],
        review_responses=[review(1, approved=True)],
    )
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool)

    first = orchestrator.run(task_id="t2", goal="add a thing", branch_name="feat/x")
    assert orchestrator.needs_clarification(first)
    assert orchestrator.clarifying_questions(first) == ["which framework?"]

    final = orchestrator.resume(task_id="t2", answer="FastAPI")

    assert final["status"] == "done"
    assert "FastAPI" in planner.plan_calls[-1]


def test_a_planner_error_that_never_recovers_is_retried_then_escalates_without_calling_the_coder():
    """Planning failures get the same bounded-retry treatment as coder/tool failures - a single
    LLM hiccup on the very first call must not kill the whole task with zero retries."""
    planner = FakePlannerAgent(plan_responses=[plan_error("model unavailable")])
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t3", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert coder.calls == []
    assert len(planner.plan_calls) == 3  # first attempt + 2 retries


def test_a_planner_error_is_retried_and_then_succeeds():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[plan_error("no complete JSON object found"), plan_ok([step])],
        review_responses=[review(1, approved=True)],
    )
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t3b", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(planner.plan_calls) == 2


def test_a_failing_coder_call_is_retried_and_then_succeeds():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[plan_ok([step])], review_responses=[review(1, approved=True)])
    coder = FakeCoderAgent([coder_error("parse failure"), coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t4", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(coder.calls) == 2


def test_a_coder_call_that_keeps_failing_escalates_after_the_retry_budget():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[plan_ok([step])])
    coder = FakeCoderAgent([coder_error("still broken")])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t5", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert len(coder.calls) == 3  # first attempt + 2 retries


def test_a_failing_test_run_is_retried_via_the_coder_and_then_succeeds():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[plan_ok([step])], review_responses=[review(1, approved=True)])
    coder = FakeCoderAgent([coder_ok(1, tests_passed=False), coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t6", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(coder.calls) == 2
    # tests_passed=False on the first attempt must skip the review call entirely - review is
    # only an additional signal on top of passing tests, never consulted otherwise.
    assert planner.review_calls == [1]


def test_a_review_rejection_despite_passing_tests_is_retried():
    """This is exactly the finding recorded in REQUIREMENTS.md #8: tests passing isn't
    sufficient on its own, so a review rejection is acted on even though tests_passed=True."""
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[plan_ok([step])],
        review_responses=[review(1, approved=False, feedback="test asserts the wrong function"), review(1, approved=True)],
    )
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True), coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t7", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(coder.calls) == 2
    assert len(planner.review_calls) == 2


def test_multi_step_plan_calls_tool_agent_only_once_at_the_end():
    steps = [PlanStep(step_id=1, description="step one"), PlanStep(step_id=2, description="step two")]
    planner = FakePlannerAgent(
        plan_responses=[plan_ok(steps)],
        review_responses=[review(1, approved=True), review(2, approved=True)],
    )
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True, files=["a.py"]), coder_ok(2, tests_passed=True, files=["b.py"])])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool)

    result = orchestrator.run(task_id="t8", goal="two steps", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(coder.calls) == 2
    assert len(tool.commit_calls) == 1
    committed_paths = set(tool.commit_calls[0][2])
    assert committed_paths == {"a.py", "b.py"}


def test_step_budget_circuit_breaker_escalates_before_completing_even_a_simple_plan():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[plan_ok([step])], review_responses=[review(1, approved=True)])
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_orchestrator_steps=2)

    result = orchestrator.run(task_id="t9", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert "step budget" in result["error"].lower()


def test_a_tool_agent_failure_escalates():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[plan_ok([step])], review_responses=[review(1, approved=True)])
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_error("push failed"))
    orchestrator = make_orchestrator(planner, coder, tool)

    result = orchestrator.run(task_id="t10", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert "push failed" in result["error"]


def test_the_coder_is_given_the_original_goal_not_just_its_step():
    """A step like "define add()" drops details the goal carries, such as the file name the task
    names; the Coder never saw them and invented its own file names (found by inspecting failed runs)."""
    step = PlanStep(step_id=1, description="Define the add function")
    planner = FakePlannerAgent(plan_responses=[plan_ok([step])], review_responses=[review(1, approved=True)])
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))

    make_orchestrator(planner, coder, tool).run(task_id="g1", goal="Add add(a, b) in calc.py", branch_name="feat/x")

    assert coder.goals == ["Add add(a, b) in calc.py"]


def test_the_coder_gets_the_same_goal_the_planner_got_including_a_clarification_answer():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[plan_needs_clarification(["which framework?"]), plan_ok([step])],
        review_responses=[review(1, approved=True)],
    )
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool)

    orchestrator.run(task_id="g2", goal="add a thing", branch_name="feat/x")
    orchestrator.resume(task_id="g2", answer="FastAPI")

    assert coder.goals[-1] == planner.plan_calls[-1]
    assert "FastAPI" in coder.goals[-1]


def _review_loop(reviews, coder_reports, steps=None):
    steps = steps or [PlanStep(step_id=1, description="add add()")]
    planner = FakePlannerAgent(plan_responses=[plan_ok(steps)], review_responses=reviews)
    coder = FakeCoderAgent(coder_reports)
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    return planner, coder, make_orchestrator(planner, coder, tool)


def test_the_reviewer_is_given_the_original_goal():
    planner, _, orchestrator = _review_loop([review(1, approved=True)], [coder_ok(1, tests_passed=True)])

    orchestrator.run(task_id="r1", goal="Add add(a, b) in calc.py", branch_name="feat/x")

    assert planner.review_goals == ["Add add(a, b) in calc.py"]


def test_a_rejection_sends_its_feedback_to_the_coder_on_the_retry():
    """Before, a rejection re-ran the Coder with identical input, so a retry was only a re-roll."""
    _, coder, orchestrator = _review_loop(
        [review(1, approved=False, feedback="Handle b == 0."), review(1, approved=True)],
        [coder_ok(1, tests_passed=True)],
    )

    result = orchestrator.run(task_id="r2", goal="g", branch_name="feat/x")

    assert result["status"] == "done"
    assert coder.feedbacks == ["", "A reviewer rejected this: Handle b == 0."]


def test_feedback_is_cleared_once_a_step_is_approved_so_the_next_step_starts_clean():
    steps = [PlanStep(step_id=1, description="one"), PlanStep(step_id=2, description="two")]
    _, coder, orchestrator = _review_loop(
        [review(1, approved=False, feedback="Fix it."), review(1, approved=True), review(2, approved=True)],
        [coder_ok(1, tests_passed=True)],
        steps,
    )

    orchestrator.run(task_id="r3", goal="g", branch_name="feat/x")

    assert coder.feedbacks == ["", "A reviewer rejected this: Fix it.", ""]


def test_a_coder_parsing_error_sends_the_error_text_to_the_retry_instead_of_a_blind_retry():
    """Before, a malformed-JSON response (the dominant real failure mode) retried with no
    information about what was wrong with the last one."""
    _, coder, orchestrator = _review_loop(
        [review(1, approved=True)],
        [coder_error("no complete JSON object found in model response"), coder_ok(1, tests_passed=True)],
    )

    result = orchestrator.run(task_id="r4", goal="g", branch_name="feat/x")

    assert result["status"] == "done"
    assert coder.feedbacks == ["", "Your last reply could not be used: no complete JSON object found in model response"]


def test_the_coders_own_failing_tests_are_fed_back_without_a_review_call():
    """A step whose own tests fail is rejected before the reviewer is ever asked (only a passing
    tests_passed triggers review), so it used to retry blind. Now it gets told why."""
    planner, coder, orchestrator = _review_loop(
        [review(1, approved=True)],
        [
            coder_ok(1, tests_passed=False, test_output="AssertionError: assert 3 == 4"),
            coder_ok(1, tests_passed=True),
        ],
    )

    result = orchestrator.run(task_id="r5", goal="g", branch_name="feat/x")

    assert result["status"] == "done"
    assert planner.review_calls == [1]  # never asked to review the failing attempt
    assert coder.feedbacks == ["", "Your own tests failed:\nAssertionError: assert 3 == 4"]
