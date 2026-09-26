"""Response-parsing primitives shared by every agent that expects a single JSON object back from
a local model: stripping a DeepSeek-R1-style reasoning block, and pulling a complete,
brace-balanced JSON object out of surrounding prose.

Extracted out of the Planner's response parser (Phase 4) once the Coder needed the exact same
logic — duplicating a security/correctness-sensitive brace-balancing scanner across two agents
would mean two places that could drift out of sync. See REQUIREMENTS.md §8 for what this had to
handle in practice against the real local model.
"""

import re

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_CLOSING_THINK_ONLY = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)


class ResponseParsingError(ValueError):
    """Base class for every agent-specific response-parsing failure."""


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


def find_balanced_json_objects(text: str) -> list[str]:
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
    objects = find_balanced_json_objects(text)
    if not objects:
        raise ResponseParsingError("no complete JSON object found in model response")
    return objects[-1]
