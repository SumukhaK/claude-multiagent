"""Tests for parsing the Planner LLM's raw text output into a validated Plan.

The shared reasoning-stripping/JSON-extraction primitives have their own tests in
tests/agents/test_response_parsing.py — this file covers only the Planner-specific composition:
turning that extracted JSON into a validated Plan, and wrapping failures as PlanParsingError.
"""

import pytest

from multiagent.agents.planner.response_parser import PlanParsingError, parse_plan_response
from multiagent.contracts.messages import Plan


def test_parse_plan_response_handles_a_clean_json_plan():
    raw = (
        '{"kind": "plan", "goal": "add health endpoint", '
        '"steps": [{"step_id": 1, "description": "write a failing test", "edge_cases": []}], '
        '"clarifying_questions": []}'
    )

    plan = parse_plan_response(raw)

    assert isinstance(plan, Plan)
    assert plan.goal == "add health endpoint"
    assert plan.steps[0].step_id == 1


def test_parse_plan_response_strips_a_think_block_first():
    raw = (
        "<think>\nthe user wants a health endpoint, I should plan a test first\n</think>\n"
        '{"kind": "plan", "goal": "add health endpoint", "steps": [], "clarifying_questions": []}'
    )

    plan = parse_plan_response(raw)

    assert plan.goal == "add health endpoint"


def test_parse_plan_response_raises_on_malformed_json():
    with pytest.raises(PlanParsingError):
        parse_plan_response('{"kind": "plan", "goal": "x", "steps": [')


def test_parse_plan_response_raises_when_schema_does_not_match():
    with pytest.raises(PlanParsingError):
        parse_plan_response('{"kind": "plan", "steps": []}')  # missing required "goal"


def test_parse_plan_response_raises_when_no_json_present_at_all():
    with pytest.raises(PlanParsingError):
        parse_plan_response("<think>hmm</think>I'm not sure how to answer that.")
