"""Tests for parsing the Planner LLM's raw text output into a validated Plan.

DeepSeek-R1-Distill models (the local model chosen in Phase 1) emit a <think>...</think>
reasoning block before their actual answer, so the parser must strip that before looking for
JSON, and must fail loudly (not silently) on anything that still doesn't parse or validate.
"""

import pytest

from multiagent.agents.planner.response_parser import (
    PlanParsingError,
    extract_json_object,
    parse_plan_response,
    strip_reasoning_block,
)
from multiagent.contracts.messages import Plan


def test_strip_reasoning_block_removes_a_think_block():
    text = "<think>let me consider the options</think>{\"goal\": \"x\"}"

    assert strip_reasoning_block(text) == '{"goal": "x"}'


def test_strip_reasoning_block_is_a_no_op_without_one():
    text = '{"goal": "x"}'

    assert strip_reasoning_block(text) == text


def test_strip_reasoning_block_handles_a_closing_tag_with_no_opening_tag():
    """Observed live: this model's raw /completion output sometimes has only a bare </think>,
    with no opening tag, because the opening tag is normally injected by a chat template we
    aren't using on the raw completion endpoint. Treat everything before it as the think block."""
    text = "some reasoning about the task\nmore reasoning\n</think>\n" + '{"goal": "x"}'

    assert strip_reasoning_block(text) == '{"goal": "x"}'


def test_extract_json_object_pulls_json_out_of_surrounding_prose():
    text = 'Sure, here is the plan:\n{"goal": "x"}\nLet me know if that works.'

    assert extract_json_object(text) == '{"goal": "x"}'


def test_extract_json_object_raises_when_no_json_is_present():
    with pytest.raises(PlanParsingError):
        extract_json_object("I don't think I can help with that.")


def test_extract_json_object_ignores_an_earlier_unrelated_brace_fragment():
    """Observed live: the model restates the goal, which itself contains something that looks
    like a small JSON object (e.g. quoting an API response shape), before its real answer."""
    text = 'The goal mentions returning {"status": "ok"} from the endpoint.\n{"goal": "real answer"}'

    assert extract_json_object(text) == '{"goal": "real answer"}'


def test_extract_json_object_ignores_braces_inside_a_json_string_value():
    text = '{"goal": "handle the {weird} case"}'

    assert extract_json_object(text) == text


def test_extract_json_object_raises_when_only_an_unclosed_object_is_present():
    """A truncated response (ran out of max_tokens mid-answer) must fail loudly, not be silently
    treated as some other, unrelated complete fragment earlier in the text."""
    with pytest.raises(PlanParsingError):
        extract_json_object('some prose\n{"kind": "plan", "goal": "x", "steps": [{"step_id": 1,')


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
