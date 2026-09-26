"""Parses a Coder LLM's raw text response into a validated CodeChangeProposal.

Mirrors the Planner's response parser (Phase 4), reusing the same shared reasoning-stripping and
JSON-extraction primitives from multiagent.agents.response_parsing.
"""

import json

from pydantic import ValidationError

from multiagent.agents.coder.schemas import CodeChangeProposal
from multiagent.agents.response_parsing import (
    ResponseParsingError,
    extract_json_object,
    strip_reasoning_block,
)


class CodeChangeParsingError(ResponseParsingError):
    """Raised when a Coder LLM response can't be parsed into a valid CodeChangeProposal."""


def parse_code_change_response(raw_text: str) -> CodeChangeProposal:
    """Parse a Coder LLM's raw text response, or raise CodeChangeParsingError."""
    try:
        json_text = extract_json_object(strip_reasoning_block(raw_text))
    except ResponseParsingError as exc:
        raise CodeChangeParsingError(str(exc)) from exc
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise CodeChangeParsingError(f"coder response was not valid JSON: {exc}") from exc
    try:
        return CodeChangeProposal.model_validate(data)
    except ValidationError as exc:
        raise CodeChangeParsingError(
            f"coder response did not match the CodeChangeProposal schema: {exc}"
        ) from exc
