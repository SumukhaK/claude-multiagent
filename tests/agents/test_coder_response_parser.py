"""Tests for parsing the Coder LLM's raw text response into a validated CodeChangeProposal.

Mirrors the Planner's response parser (Phase 4): the shared reasoning-stripping/JSON-extraction
primitives have their own tests in tests/agents/test_response_parsing.py -- this covers only the
Coder-specific composition.
"""

import pytest

from multiagent.agents.coder.response_parser import (
    CodeChangeParsingError,
    parse_code_change_response,
)
from multiagent.agents.coder.schemas import CodeChangeProposal


def test_parse_code_change_response_handles_a_clean_json_proposal():
    raw = (
        '{"kind": "code_change", "step_id": 1, '
        '"test_files": [{"path": "tests/test_x.py", "content": "def test_x(): pass"}], '
        '"implementation_files": [{"path": "src/x.py", "content": "def x(): pass"}], '
        '"summary": "added x"}'
    )

    proposal = parse_code_change_response(raw)

    assert isinstance(proposal, CodeChangeProposal)
    assert proposal.step_id == 1
    assert proposal.test_files[0].path == "tests/test_x.py"


def test_parse_code_change_response_strips_a_think_block_first():
    raw = (
        "<think>I should write a test first</think>"
        '{"kind": "code_change", "step_id": 1, '
        '"test_files": [{"path": "tests/test_x.py", "content": "def test_x(): pass"}], '
        '"implementation_files": [], "summary": "added a test"}'
    )

    proposal = parse_code_change_response(raw)

    assert proposal.summary == "added a test"


def test_parse_code_change_response_raises_on_malformed_json():
    with pytest.raises(CodeChangeParsingError):
        parse_code_change_response('{"kind": "code_change", "step_id": 1, "test_files": [')


def test_parse_code_change_response_raises_when_no_test_files_are_proposed():
    """TDD enforcement surfaces here as a parsing failure, not a silently-accepted proposal."""
    raw = (
        '{"kind": "code_change", "step_id": 1, "test_files": [], '
        '"implementation_files": [{"path": "src/x.py", "content": "def x(): pass"}], '
        '"summary": "added x without a test"}'
    )

    with pytest.raises(CodeChangeParsingError, match="TDD"):
        parse_code_change_response(raw)


def test_parse_code_change_response_raises_when_no_json_present_at_all():
    with pytest.raises(CodeChangeParsingError):
        parse_code_change_response("<think>hmm</think>I'm not sure how to answer that.")
