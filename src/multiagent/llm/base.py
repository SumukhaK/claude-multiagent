"""Shared response type for every local LLM backend (llama.cpp, Ollama)."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    """A normalized result from any backend, regardless of its native response shape."""

    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_seconds: float


class LLMClient(Protocol):
    """Minimal interface every backend client implements, so agents don't care which one they use."""

    def generate(
        self, prompt: str, *, max_tokens: int = 512, json_schema: dict | None = None
    ) -> LLMResponse:
        """`json_schema`, when given, asks the backend to constrain decoding to that schema."""
        ...
