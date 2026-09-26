"""End-to-end tests for the LangGraph orchestrator: the plan -> implement -> review loop, the
human-in-the-loop clarification interrupt, bounded per-step retries, and the hard step-budget
circuit breaker.

Uses fake Planner/Coder/Tool agents (queued canned AgentMessages) rather than the real agents --
each agent's own internals already have dedicated tests in their own phases. These tests are
about the orchestrator's routing and state logic: does it advance, retry, escalate, or pause for
a human at the right times.
"""

from multiagent.contracts.messages import (
    AgentMessage,
    AgentName,
    CodeChangeReport,
    MessageStatus,
    Plan,
    PlanStep,
    StepReview,
    ToolExecutionReport,
)
from multiagent.orchestrator.orchestrator import Orchestrator


def _plan_ok(steps):
    return AgentMessage(
        agent=AgentName.PLANNER, task_id="t", status=MessageStatus.OK,
        payload=Plan(goal="goal", steps=steps, clarifying_questions=[]),
    )


def _plan_needs_clarification(questions):
    return AgentMessage(
        agent=AgentName.PLANNER, task_id="t", status=MessageStatus.NEEDS_CLARIFICATION,
        payload=Plan(goal="goal", steps=[], clarifying_questions=questions),
    )


def _plan_error(message):
    return AgentMessage(agent=AgentName.PLANNER, task_id="t", status=MessageStatus.ERROR, error=message)


def _coder_ok(step_id, tests_passed, files=None, summary="did the thing"):
    return AgentMessage(
        agent=AgentName.CODER, task_id="t", status=MessageStatus.OK,
        payload=CodeChangeReport(
            step_id=step_id, files_changed=files or ["a.py"], tests_added=["test_a.py"],
            tests_passed=tests_passed, summary=summary,
        ),
    )


def _coder_error(message):
    return AgentMessage(agent=AgentName.CODER, task_id="t", status=MessageStatus.ERROR, error=message)


def _review(step_id, approved, feedback="ok"):
    return AgentMessage(
        agent=AgentName.PLANNER, task_id="t", status=MessageStatus.OK,
        payload=StepReview(step_id=step_id, approved=approved, feedback=feedback),
    )


def _tool_ok(action, details=""):
    return AgentMessage(
        agent=AgentName.TOOL, task_id="t", status=MessageStatus.OK,
        payload=ToolExecutionReport(action=action, success=True, details=details),
    )


def _tool_error(message):
    return AgentMessage(agent=AgentName.TOOL, task_id="t", status=MessageStatus.ERROR, error=message)


class FakePlannerAgent:
    def __init__(self, plan_responses, review_responses=None):
        self._plan_responses = list(plan_responses)
        self._review_responses = list(review_responses or [])
        self.plan_calls = []
        self.review_calls = []

    def create_plan(self, goal, code_context=""):
        self.plan_calls.append(goal)
        return self._plan_responses.pop(0) if len(self._plan_responses) > 1 else self._plan_responses[0]

    def review_step(self, step, report, code_context=""):
        self.review_calls.append(step.step_id)
        return self._review_responses.pop(0) if len(self._review_responses) > 1 else self._review_responses[0]


class FakeCoderAgent:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def implement_step(self, step, code_context=""):
        self.calls.append(step.step_id)
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]


class FakeToolAgent:
    def __init__(self, commit_response, pr_response=None):
        self.commit_response = commit_response
        self.pr_response = pr_response
        self.commit_calls = []
        self.pr_calls = []

    def commit_and_push(self, branch, summary, paths):
        self.commit_calls.append((branch, summary, tuple(paths)))
        return self.commit_response

    def open_pull_request(self, title, body, base="main"):
        self.pr_calls.append((title, body, base))
        return self.pr_response


def make_orchestrator(planner, coder, tool, max_retries_per_step=2, max_orchestrator_steps=25):
    return Orchestrator(
        planner_agent=planner,
        coder_agent=coder,
        tool_agent=tool,
        max_retries_per_step=max_retries_per_step,
        max_orchestrator_steps=max_orchestrator_steps,
    )


def test_happy_path_single_step_reaches_done():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[_plan_ok([step])], review_responses=[_review(1, approved=True)]
    )
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool)

    result = orchestrator.run(task_id="t1", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(tool.commit_calls) == 1
    assert len(tool.pr_calls) == 1


def test_clarification_interrupt_then_resume_produces_a_plan():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[_plan_needs_clarification(["which framework?"]), _plan_ok([step])],
        review_responses=[_review(1, approved=True)],
    )
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
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
    planner = FakePlannerAgent(plan_responses=[_plan_error("model unavailable")])
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t3", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert coder.calls == []
    assert len(planner.plan_calls) == 3  # first attempt + 2 retries


def test_a_planner_error_is_retried_and_then_succeeds():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(
        plan_responses=[_plan_error("no complete JSON object found"), _plan_ok([step])],
        review_responses=[_review(1, approved=True)],
    )
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t3b", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(planner.plan_calls) == 2


def test_a_failing_coder_call_is_retried_and_then_succeeds():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[_plan_ok([step])], review_responses=[_review(1, approved=True)])
    coder = FakeCoderAgent([_coder_error("parse failure"), _coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t4", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(coder.calls) == 2


def test_a_coder_call_that_keeps_failing_escalates_after_the_retry_budget():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[_plan_ok([step])])
    coder = FakeCoderAgent([_coder_error("still broken")])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t5", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert len(coder.calls) == 3  # first attempt + 2 retries


def test_a_failing_test_run_is_retried_via_the_coder_and_then_succeeds():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[_plan_ok([step])], review_responses=[_review(1, approved=True)])
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=False), _coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
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
        plan_responses=[_plan_ok([step])],
        review_responses=[_review(1, approved=False, feedback="test asserts the wrong function"), _review(1, approved=True)],
    )
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True), _coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_retries_per_step=2)

    result = orchestrator.run(task_id="t7", goal="add add()", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(coder.calls) == 2
    assert len(planner.review_calls) == 2


def test_multi_step_plan_calls_tool_agent_only_once_at_the_end():
    steps = [PlanStep(step_id=1, description="step one"), PlanStep(step_id=2, description="step two")]
    planner = FakePlannerAgent(
        plan_responses=[_plan_ok(steps)],
        review_responses=[_review(1, approved=True), _review(2, approved=True)],
    )
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True, files=["a.py"]), _coder_ok(2, tests_passed=True, files=["b.py"])])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool)

    result = orchestrator.run(task_id="t8", goal="two steps", branch_name="feat/x")

    assert result["status"] == "done"
    assert len(coder.calls) == 2
    assert len(tool.commit_calls) == 1
    committed_paths = set(tool.commit_calls[0][2])
    assert committed_paths == {"a.py", "b.py"}


def test_step_budget_circuit_breaker_escalates_before_completing_even_a_simple_plan():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[_plan_ok([step])], review_responses=[_review(1, approved=True)])
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_ok("commit_and_push"), pr_response=_tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, max_orchestrator_steps=2)

    result = orchestrator.run(task_id="t9", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert "step budget" in result["error"].lower()


def test_a_tool_agent_failure_escalates():
    step = PlanStep(step_id=1, description="add add()")
    planner = FakePlannerAgent(plan_responses=[_plan_ok([step])], review_responses=[_review(1, approved=True)])
    coder = FakeCoderAgent([_coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=_tool_error("push failed"))
    orchestrator = make_orchestrator(planner, coder, tool)

    result = orchestrator.run(task_id="t10", goal="add add()", branch_name="feat/x")

    assert result["status"] == "failed"
    assert "push failed" in result["error"]
