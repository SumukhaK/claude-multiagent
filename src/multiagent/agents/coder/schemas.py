"""Internal schema for what the Coder's LLM proposes.

Unlike Plan (multiagent/contracts/messages.py), which the orchestrator and Planning agent see as
an AgentMessage payload, this never leaves the Coding agent: it's parsed from the LLM's raw
response, used to write files and run tests, and then converted into a CodeChangeReport (which
IS part of the inter-agent contract) before anything else sees it.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ProposedFile(BaseModel):
    """One file the Coder's LLM wants written, verbatim."""

    path: str
    content: str


class CodeChangeProposal(BaseModel):
    """The Coder's raw proposal for one plan step: a failing test first, then the implementation."""

    kind: Literal["code_change"] = "code_change"
    step_id: int
    # min_length lives in the schema (not a Python validator) so constrained decoding enforces it
    test_files: list[ProposedFile] = Field(min_length=1)  # TDD is mandatory
    implementation_files: list[ProposedFile] = Field(default_factory=list)
    summary: str
