"""Parses a Planner LLM's raw text response into a validated Plan.

The local model (DeepSeek-R1-Distill-Qwen-1.5B, chosen in Phase 1) is a reasoning model that
emits a <think>...</think> chain-of-thought block before its actual answer, and small models in
general sometimes wrap JSON in prose rather than returning it bare. This module strips both
before validating, and raises loudly (PlanParsingError) rather than silently returning a
half-parsed or wrong-shaped Plan.
"""

import json
import re

from pydantic import ValidationError

from multiagent.contracts.messages import Plan

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CLOSING_THINK_ONLY = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)


class PlanParsingError(ValueError):
    """Raised when a Planner LLM response can't be parsed into a valid Plan."""


def strip_reasoning_block(text: str) -> str:
    """Remove a DeepSeek-R1-style reasoning block, if present.

    Handles two shapes seen from this model in practice: a matched <think>...</think> pair, and
    -- observed live against the raw /completion endpoint, which doesn't apply a chat template --
    a bare closing </think> with no opening tag at all, in which case everything before it is
    the reasoning block.
    """
    lowered = text.lower()
    if "<think>" in lowered and "</think>" in lowered:
        return _THINK_BLOCK.sub("", text).strip()
    if "</think>" in lowered:
        return _CLOSING_THINK_ONLY.sub("", text).strip()
    return text.strip()


def _find_balanced_json_objects(text: str) -> list[str]:
    """Find every complete, brace-balanced {...} object in text, ignoring braces inside strings.

    A naive greedy regex (first "{" to last "}") breaks as soon as the text contains more than
    one brace-shaped fragment -- e.g. a model restating "returns {\"status\": \"ok\"}" in prose
    before its real answer -- because it swallows everything in between as one invalid blob.
    This scans char-by-char instead, so unrelated fragments and string-internal braces don't
    corrupt the match.
    """
    objects = []
    depth = 0
    start = None
    in_string = False
    escape = False
    for i, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(text[start : i + 1])
                start = None
    return objects


def extract_json_object(text: str) -> str:
    """Pull the last complete, balanced {...} object out of any surrounding prose.

    The *last* one is preferred because a model's real answer typically comes after any earlier
    restatement of the task; a truncated final answer (ran out of max_tokens) never balances, so
    it's correctly excluded rather than silently matched against.
    """
    objects = _find_balanced_json_objects(text)
    if not objects:
        raise PlanParsingError("no complete JSON object found in planner response")
    return objects[-1]


def parse_plan_response(raw_text: str) -> Plan:
    """Parse a Planner LLM's raw text response into a validated Plan, or raise PlanParsingError."""
    json_text = extract_json_object(strip_reasoning_block(raw_text))
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise PlanParsingError(f"planner response was not valid JSON: {exc}") from exc
    try:
        return Plan.model_validate(data)
    except ValidationError as exc:
        raise PlanParsingError(f"planner response did not match the Plan schema: {exc}") from exc
