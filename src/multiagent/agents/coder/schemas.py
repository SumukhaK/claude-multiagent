"""Internal schema for what the Coder's LLM proposes.

Unlike Plan (multiagent/contracts/messages.py), which the orchestrator and Planning agent see as
an AgentMessage payload, this never leaves the Coding agent: it's parsed from the LLM's raw
response, used to write files and run tests, and then converted into a CodeChangeReport (which
IS part of the inter-agent contract) before anything else sees it.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ProposedFile(BaseModel):
    """One file the Coder's LLM wants written, verbatim."""

    path: str
    content: str


class CodeChangeProposal(BaseModel):
    """The Coder's raw proposal for one plan step: a failing test first, then the implementation."""

    kind: Literal["code_change"] = "code_change"
    step_id: int
    test_files: list[ProposedFile] = Field(default_factory=list)
    implementation_files: list[ProposedFile] = Field(default_factory=list)
    summary: str

    @model_validator(mode="after")
    def _tdd_requires_at_least_one_test_file(self) -> "CodeChangeProposal":
        if not self.test_files:
            raise ValueError(
                "a code change proposal must include at least one test file (TDD is mandatory)"
            )
        return self
