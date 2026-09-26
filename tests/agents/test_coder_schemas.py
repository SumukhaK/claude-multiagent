"""Tests for the Coder's internal code-change-proposal schema.

Unlike Plan (contracts/messages.py), this is not part of the inter-agent contract -- it never
leaves the Coding agent, and the orchestrator/Planner only ever see the resulting
CodeChangeReport. TDD is enforced structurally here: a proposal with no test files is invalid.
"""

import pytest
from pydantic import ValidationError

from multiagent.agents.coder.schemas import CodeChangeProposal, ProposedFile


def test_a_valid_proposal_with_tests_and_implementation_parses():
    proposal = CodeChangeProposal.model_validate(
        {
            "kind": "code_change",
            "step_id": 1,
            "test_files": [{"path": "tests/test_x.py", "content": "def test_x(): pass"}],
            "implementation_files": [{"path": "src/x.py", "content": "def x(): pass"}],
            "summary": "added x",
        }
    )

    assert proposal.test_files == [ProposedFile(path="tests/test_x.py", content="def test_x(): pass")]
    assert proposal.implementation_files[0].path == "src/x.py"


def test_a_proposal_with_no_test_files_is_rejected():
    """TDD is mandatory, not just requested -- enforced at the schema level."""
    with pytest.raises(ValidationError, match="TDD"):
        CodeChangeProposal.model_validate(
            {
                "kind": "code_change",
                "step_id": 1,
                "test_files": [],
                "implementation_files": [{"path": "src/x.py", "content": "def x(): pass"}],
                "summary": "added x",
            }
        )


def test_a_proposal_with_tests_but_no_implementation_files_is_valid():
    """Unusual (e.g. a step that only adds test coverage for existing behaviour) but not invalid."""
    proposal = CodeChangeProposal.model_validate(
        {
            "kind": "code_change",
            "step_id": 1,
            "test_files": [{"path": "tests/test_x.py", "content": "def test_x(): pass"}],
            "implementation_files": [],
            "summary": "covered existing behaviour",
        }
    )

    assert proposal.implementation_files == []


def test_proposed_file_requires_both_path_and_content():
    with pytest.raises(ValidationError):
        ProposedFile.model_validate({"path": "src/x.py"})
