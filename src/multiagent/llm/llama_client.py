"""HTTP client for the local llama-server, used by the Planner and Coder agents."""

import time

import httpx

from multiagent.llm.base import LLMResponse


class LlamaServerClient:
    """Thin wrapper around llama-server's native /completion endpoint."""

    def __init__(self, base_url: str, timeout: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def generate(
        self, prompt: str, *, max_tokens: int = 512, client: httpx.Client | None = None
    ) -> LLMResponse:
        started = time.monotonic()
        owns_client = client is None
        http_client = client or httpx.Client(timeout=self._timeout)
        try:
            response = http_client.post(
                f"{self._base_url}/completion",
                json={"prompt": prompt, "n_predict": max_tokens, "stream": False},
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if owns_client:
                http_client.close()
        elapsed = time.monotonic() - started
        return LLMResponse(
            text=data.get("content", ""),
            prompt_tokens=data.get("tokens_evaluated", 0),
            completion_tokens=data.get("tokens_predicted", 0),
            latency_seconds=elapsed,
        )
