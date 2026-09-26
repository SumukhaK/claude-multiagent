"""Tests for the response-parsing primitives shared by every agent that expects a single JSON
object back from a local model (stripping a reasoning block, extracting balanced JSON).

Extracted out of the Planner's response parser (Phase 4) so the Coder doesn't duplicate the same
security/correctness-sensitive brace-balancing logic in a second implementation.
"""

import pytest

from multiagent.agents.response_parsing import (
    ResponseParsingError,
    extract_json_object,
    find_balanced_json_objects,
    strip_reasoning_block,
)


def test_strip_reasoning_block_removes_a_think_block():
    text = "<think>let me consider the options</think>{\"goal\": \"x\"}"

    assert strip_reasoning_block(text) == '{"goal": "x"}'


def test_strip_reasoning_block_is_a_no_op_without_one():
    text = '{"goal": "x"}'

    assert strip_reasoning_block(text) == text


def test_strip_reasoning_block_handles_a_closing_tag_with_no_opening_tag():
    """Observed live against this model's raw /completion output (Phase 4): no chat template is
    applied, so the opening <think> tag that would normally be injected by one never appears."""
    text = "some reasoning about the task\nmore reasoning\n</think>\n" + '{"goal": "x"}'

    assert strip_reasoning_block(text) == '{"goal": "x"}'


def test_find_balanced_json_objects_returns_every_complete_object_in_order():
    text = 'prefix {"a": 1} middle {"b": 2} suffix'

    assert find_balanced_json_objects(text) == ['{"a": 1}', '{"b": 2}']


def test_find_balanced_json_objects_ignores_braces_inside_string_values():
    text = '{"goal": "handle the {weird} case"}'

    assert find_balanced_json_objects(text) == [text]


def test_find_balanced_json_objects_excludes_an_unclosed_trailing_object():
    text = 'some prose\n{"kind": "plan", "goal": "x", "steps": [{"step_id": 1,'

    assert find_balanced_json_objects(text) == []


def test_find_balanced_json_objects_returns_empty_list_for_no_braces_at_all():
    assert find_balanced_json_objects("no json here") == []


def test_extract_json_object_pulls_json_out_of_surrounding_prose():
    text = 'Sure, here is the plan:\n{"goal": "x"}\nLet me know if that works.'

    assert extract_json_object(text) == '{"goal": "x"}'


def test_extract_json_object_prefers_the_last_complete_object():
    """A model's real answer typically comes after any earlier restatement of the task."""
    text = 'The goal mentions returning {"status": "ok"} from the endpoint.\n{"goal": "real answer"}'

    assert extract_json_object(text) == '{"goal": "real answer"}'


def test_extract_json_object_raises_when_no_json_is_present():
    with pytest.raises(ResponseParsingError):
        extract_json_object("I don't think I can help with that.")


def test_extract_json_object_raises_when_only_an_unclosed_object_is_present():
    """A truncated response (ran out of max_tokens mid-answer) must fail loudly, not be silently
    treated as some other, unrelated complete fragment earlier in the text."""
    with pytest.raises(ResponseParsingError):
        extract_json_object('some prose\n{"kind": "plan", "goal": "x", "steps": [{"step_id": 1,')
