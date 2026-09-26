"""Shared canned messages and fake agents for the orchestrator tests: queued AgentMessages
stand in for the real Planner/Coder/Tool agents, whose own internals are tested in their phases."""

from multiagent.contracts.messages import (
    AgentMessage,
    AgentName,
    CodeChangeReport,
    MessageStatus,
    Plan,
    StepReview,
    ToolExecutionReport,
)
from multiagent.orchestrator.orchestrator import Orchestrator


def plan_ok(steps):
    return AgentMessage(
        agent=AgentName.PLANNER, task_id="t", status=MessageStatus.OK,
        payload=Plan(goal="goal", steps=steps, clarifying_questions=[]),
    )


def plan_needs_clarification(questions):
    return AgentMessage(
        agent=AgentName.PLANNER, task_id="t", status=MessageStatus.NEEDS_CLARIFICATION,
        payload=Plan(goal="goal", steps=[], clarifying_questions=questions),
    )


def plan_error(message):
    return AgentMessage(agent=AgentName.PLANNER, task_id="t", status=MessageStatus.ERROR, error=message)


def coder_ok(step_id, tests_passed, files=None, summary="did the thing"):
    return AgentMessage(
        agent=AgentName.CODER, task_id="t", status=MessageStatus.OK,
        payload=CodeChangeReport(
            step_id=step_id, files_changed=files or ["a.py"], tests_added=["test_a.py"],
            tests_passed=tests_passed, summary=summary,
        ),
    )


def coder_error(message):
    return AgentMessage(agent=AgentName.CODER, task_id="t", status=MessageStatus.ERROR, error=message)


def review(step_id, approved, feedback="ok"):
    return AgentMessage(
        agent=AgentName.PLANNER, task_id="t", status=MessageStatus.OK,
        payload=StepReview(step_id=step_id, approved=approved, feedback=feedback),
    )


def tool_ok(action, details=""):
    return AgentMessage(
        agent=AgentName.TOOL, task_id="t", status=MessageStatus.OK,
        payload=ToolExecutionReport(action=action, success=True, details=details),
    )


def tool_error(message):
    return AgentMessage(agent=AgentName.TOOL, task_id="t", status=MessageStatus.ERROR, error=message)


class FakePlannerAgent:
    def __init__(self, plan_responses, review_responses=None):
        self._plan_responses = list(plan_responses)
        self._review_responses = list(review_responses or [])
        self.plan_calls = []
        self.review_calls = []
        self.plan_contexts = []
        self.review_contexts = []

    def create_plan(self, goal, code_context=""):
        self.plan_calls.append(goal)
        self.plan_contexts.append(code_context)
        return self._plan_responses.pop(0) if len(self._plan_responses) > 1 else self._plan_responses[0]

    def review_step(self, step, report, code_context=""):
        self.review_calls.append(step.step_id)
        self.review_contexts.append(code_context)
        return self._review_responses.pop(0) if len(self._review_responses) > 1 else self._review_responses[0]


class FakeCoderAgent:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.contexts = []

    def implement_step(self, step, code_context=""):
        self.calls.append(step.step_id)
        self.contexts.append(code_context)
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


def make_orchestrator(planner, coder, tool, max_retries_per_step=2, max_orchestrator_steps=25, memory=None):
    return Orchestrator(
        planner_agent=planner,
        coder_agent=coder,
        tool_agent=tool,
        max_retries_per_step=max_retries_per_step,
        max_orchestrator_steps=max_orchestrator_steps,
        memory=memory,
    )


class FakeMemory:
    """Stands in for MemoryStore: records what was recalled/remembered, returns canned context."""

    def __init__(self, context=""):
        self.context = context
        self.recall_queries = []
        self.remembered = []

    def recall_context(self, query):
        self.recall_queries.append(query)
        return self.context

    def remember(self, text, kind):
        self.remembered.append((kind, text))
        return True

    def kinds(self):
        return [kind for kind, _ in self.remembered]
