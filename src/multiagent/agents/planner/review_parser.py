"""Parses the Planner's step-review response into a validated StepReview.

Mirrors the plan/code-change response parsers, reusing the same shared reasoning-stripping and
JSON-extraction primitives from multiagent.agents.response_parsing.
"""

import json

from pydantic import ValidationError

from multiagent.agents.response_parsing import (
    ResponseParsingError,
    extract_json_object,
    strip_reasoning_block,
)
from multiagent.contracts.messages import StepReview


class StepReviewParsingError(ResponseParsingError):
    """Raised when a Planner review response can't be parsed into a valid StepReview."""


def parse_step_review_response(raw_text: str) -> StepReview:
    """Parse a Planner review LLM's raw text response, or raise StepReviewParsingError."""
    try:
        json_text = extract_json_object(strip_reasoning_block(raw_text))
    except ResponseParsingError as exc:
        raise StepReviewParsingError(str(exc)) from exc
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise StepReviewParsingError(f"review response was not valid JSON: {exc}") from exc
    try:
        return StepReview.model_validate(data)
    except ValidationError as exc:
        raise StepReviewParsingError(f"review response did not match the StepReview schema: {exc}") from exc
