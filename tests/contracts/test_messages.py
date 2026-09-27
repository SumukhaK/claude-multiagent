"""Tests for the strict inter-agent JSON message contract.

Per REQUIREMENTS.md §4: every message between the orchestrator and a sub-agent must be a
validated pydantic model, never a free-form dict, so a malformed message fails loudly.
"""

import pytest
from pydantic import ValidationError

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


def test_planner_ok_message_with_plan_payload_round_trips_through_json():
    message = AgentMessage.model_validate(
        {
            "agent": "planner",
            "task_id": "task-1",
            "status": "ok",
            "payload": {
                "kind": "plan",
                "goal": "add a health endpoint",
                "steps": [{"step_id": 1, "description": "write a failing test", "edge_cases": ["empty body"]}],
                "clarifying_questions": [],
            },
        }
    )

    assert message.agent == AgentName.PLANNER
    assert isinstance(message.payload, Plan)
    assert message.payload.steps[0] == PlanStep(step_id=1, description="write a failing test", edge_cases=["empty body"])


def test_coder_ok_message_with_code_change_report_payload():
    message = AgentMessage.model_validate(
        {
            "agent": "coder",
            "task_id": "task-1",
            "status": "ok",
            "payload": {
                "kind": "code_change_report",
                "step_id": 1,
                "files_changed": ["src/app.py"],
                "tests_added": ["tests/test_app.py"],
                "tests_passed": True,
                "summary": "added the health endpoint",
            },
        }
    )

    assert isinstance(message.payload, CodeChangeReport)
    assert message.payload.tests_passed is True


def test_tool_ok_message_with_tool_execution_report_payload():
    message = AgentMessage.model_validate(
        {
            "agent": "tool",
            "task_id": "task-1",
            "status": "ok",
            "payload": {"kind": "tool_execution_report", "action": "git push", "success": True, "details": "pushed to origin"},
        }
    )

    assert isinstance(message.payload, ToolExecutionReport)
    assert message.payload.action == "git push"


def test_planner_ok_message_with_step_review_payload():
    message = AgentMessage.model_validate(
        {
            "agent": "planner",
            "task_id": "task-1",
            "status": "ok",
            "payload": {"kind": "step_review", "step_id": 1, "approved": True, "feedback": "looks correct"},
        }
    )

    assert isinstance(message.payload, StepReview)
    assert message.payload.approved is True


def test_error_status_requires_a_non_empty_error_message():
    with pytest.raises(ValidationError):
        AgentMessage.model_validate({"agent": "coder", "task_id": "task-1", "status": "error"})


def test_error_field_must_not_be_set_unless_status_is_error():
    with pytest.raises(ValidationError):
        AgentMessage.model_validate(
            {"agent": "coder", "task_id": "task-1", "status": "ok", "error": "should not be here"}
        )


def test_error_status_with_message_is_valid():
    message = AgentMessage.model_validate(
        {"agent": "coder", "task_id": "task-1", "status": "error", "error": "tests failed after 2 retries"}
    )

    assert message.status == MessageStatus.ERROR
    assert message.error == "tests failed after 2 retries"


def test_retry_count_cannot_be_negative():
    with pytest.raises(ValidationError):
        AgentMessage.model_validate({"agent": "coder", "task_id": "task-1", "status": "ok", "retry_count": -1})


def test_needs_clarification_message_needs_no_payload():
    message = AgentMessage.model_validate(
        {"agent": "planner", "task_id": "task-1", "status": "needs_clarification"}
    )

    assert message.payload is None


def test_unknown_agent_name_is_rejected():
    with pytest.raises(ValidationError):
        AgentMessage.model_validate({"agent": "reviewer", "task_id": "task-1", "status": "ok"})


def test_plan_payload_missing_required_field_is_rejected():
    with pytest.raises(ValidationError):
        AgentMessage.model_validate(
            {
                "agent": "planner",
                "task_id": "task-1",
                "status": "ok",
                "payload": {"kind": "plan", "steps": []},
            }
        )


def test_payload_kind_must_match_a_known_discriminator():
    with pytest.raises(ValidationError):
        AgentMessage.model_validate(
            {"agent": "planner", "task_id": "task-1", "status": "ok", "payload": {"kind": "not_a_real_kind"}}
        )


def test_a_code_change_report_can_carry_the_file_contents_and_defaults_to_none():
    from multiagent.contracts.messages import CodeChangeReport

    bare = CodeChangeReport(step_id=1, files_changed=["a.py"], tests_added=[], tests_passed=True, summary="s")
    full = CodeChangeReport(
        step_id=1, files_changed=["a.py"], tests_added=[], tests_passed=True, summary="s",
        file_contents={"a.py": "x = 1\n"},
    )

    assert bare.file_contents == {}
    assert full.file_contents == {"a.py": "x = 1\n"}
