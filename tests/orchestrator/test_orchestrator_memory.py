"""Tests for the orchestrator's memory wiring: what gets recalled into the agents' context, and
what is (and deliberately isn't) remembered afterwards.

Rule under test: only *verified* outcomes are remembered -- an approved step (tests passed), the
user's clarification answers, a completed task. Never plans (unverified proposals) or failed
attempts, which would poison future recall.
"""

from multiagent.contracts.messages import PlanStep
from tests.orchestrator.fakes import (
    FakeCoderAgent,
    FakeMemory,
    FakePlannerAgent,
    FakeToolAgent,
    coder_error,
    coder_ok,
    make_orchestrator,
    plan_needs_clarification,
    plan_ok,
    review,
    tool_ok,
)

STEP = PlanStep(step_id=1, description="add add()")


def build(memory, *, plan=None, coder=None, planner_reviews=None, code_context=""):
    planner = FakePlannerAgent(
        plan_responses=plan or [plan_ok([STEP])],
        review_responses=planner_reviews or [review(1, approved=True)],
    )
    coder = coder or FakeCoderAgent([coder_ok(1, tests_passed=True, files=["calc.py"], summary="added add()")])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, memory=memory)
    result = orchestrator.run(task_id="t", goal="add add()", branch_name="feat/x", code_context=code_context)
    return planner, coder, result


def test_planner_gets_recalled_memory_queried_by_the_goal():
    memory = FakeMemory("MEMORY-BLOCK")

    planner, _, _ = build(memory)

    assert "MEMORY-BLOCK" in planner.plan_contexts[0]
    assert memory.recall_queries[0] == "add add()"


def test_recalled_memory_is_appended_to_the_existing_code_context():
    planner, _, _ = build(FakeMemory("MEMORY-BLOCK"), code_context="EXISTING CODE")

    assert planner.plan_contexts[0] == "EXISTING CODE\n\nMEMORY-BLOCK"


def test_empty_recall_leaves_the_code_context_untouched():
    planner, coder, _ = build(FakeMemory(""), code_context="EXISTING CODE")

    assert planner.plan_contexts[0] == "EXISTING CODE"
    assert coder.contexts[0] == "EXISTING CODE"


def test_coder_and_reviewer_get_recalled_memory_queried_by_the_step():
    memory = FakeMemory("MEMORY-BLOCK")

    planner, coder, _ = build(memory)

    assert "MEMORY-BLOCK" in coder.contexts[0]
    assert "MEMORY-BLOCK" in planner.review_contexts[0]
    assert memory.recall_queries.count("add add()") >= 3  # plan (goal) + implement + review


def test_an_approved_step_is_remembered_with_its_description_summary_and_files():
    memory = FakeMemory()

    build(memory)

    step_memories = [text for kind, text in memory.remembered if kind == "step_summary"]
    assert len(step_memories) == 1
    assert "add add()" in step_memories[0]
    assert "added add()" in step_memories[0]
    assert "calc.py" in step_memories[0]


def test_a_failed_test_run_is_not_remembered():
    memory = FakeMemory()
    coder = FakeCoderAgent([coder_ok(1, tests_passed=False), coder_ok(1, tests_passed=True)])

    build(memory, coder=coder)

    assert memory.kinds().count("step_summary") == 1  # only the passing attempt


def test_a_review_rejected_step_is_not_remembered():
    memory = FakeMemory()
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True), coder_ok(1, tests_passed=True)])
    reviews = [review(1, approved=False, feedback="wrong test"), review(1, approved=True)]

    build(memory, coder=coder, planner_reviews=reviews)

    assert memory.kinds().count("step_summary") == 1


def test_plans_are_never_remembered():
    memory = FakeMemory()

    build(memory)

    assert "plan" not in memory.kinds()


def test_a_clarification_answer_is_remembered_once_with_its_questions():
    memory = FakeMemory()
    planner = FakePlannerAgent(
        plan_responses=[plan_needs_clarification(["which framework?"]), plan_ok([STEP])],
        review_responses=[review(1, approved=True)],
    )
    coder = FakeCoderAgent([coder_ok(1, tests_passed=True)])
    tool = FakeToolAgent(commit_response=tool_ok("commit_and_push"), pr_response=tool_ok("create_pull_request"))
    orchestrator = make_orchestrator(planner, coder, tool, memory=memory)

    orchestrator.run(task_id="t", goal="add add()", branch_name="feat/x")
    assert memory.kinds().count("clarification") == 0  # nothing yet: still waiting for the human
    orchestrator.resume(task_id="t", answer="FastAPI")

    clarifications = [text for kind, text in memory.remembered if kind == "clarification"]
    assert len(clarifications) == 1
    assert "which framework?" in clarifications[0]
    assert "FastAPI" in clarifications[0]


def test_a_completed_task_is_remembered():
    memory = FakeMemory()

    build(memory)

    tasks = [text for kind, text in memory.remembered if kind == "task"]
    assert len(tasks) == 1
    assert "add add()" in tasks[0]
    assert "feat/x" in tasks[0]


def test_an_escalated_task_is_not_remembered_as_completed():
    memory = FakeMemory()

    _, _, result = build(memory, coder=FakeCoderAgent([coder_error("still broken")]))

    assert result["status"] == "failed"
    assert "task" not in memory.kinds()


def test_the_completed_task_memory_counts_plan_steps_not_retry_attempts():
    memory = FakeMemory()
    coder = FakeCoderAgent([coder_ok(1, tests_passed=False), coder_ok(1, tests_passed=True)])

    build(memory, coder=coder)

    task = next(text for kind, text in memory.remembered if kind == "task")
    assert "1 steps" in task  # one plan step, even though the coder was called twice
