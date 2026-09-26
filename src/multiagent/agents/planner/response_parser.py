"""Parses a Planner LLM's raw text response into a validated Plan.

The reasoning-stripping and JSON-extraction primitives live in multiagent.agents.response_parsing
(shared with the Coder, which needs the exact same handling of this model's <think> block and
malformed/truncated JSON). This module only adds the Planner-specific piece: validating the
extracted JSON against the Plan schema and reporting any failure as PlanParsingError.
"""

import json

from pydantic import ValidationError

from multiagent.agents.response_parsing import (
    ResponseParsingError,
    extract_json_object,
    strip_reasoning_block,
)
from multiagent.contracts.messages import Plan


class PlanParsingError(ResponseParsingError):
    """Raised when a Planner LLM response can't be parsed into a valid Plan."""


def parse_plan_response(raw_text: str) -> Plan:
    """Parse a Planner LLM's raw text response into a validated Plan, or raise PlanParsingError."""
    try:
        json_text = extract_json_object(strip_reasoning_block(raw_text))
    except ResponseParsingError as exc:
        raise PlanParsingError(str(exc)) from exc
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise PlanParsingError(f"planner response was not valid JSON: {exc}") from exc
    try:
        return Plan.model_validate(data)
    except ValidationError as exc:
        raise PlanParsingError(f"planner response did not match the Plan schema: {exc}") from exc
