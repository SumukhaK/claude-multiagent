"""HTTP client for the local llama-server, used by the Planner and Coder agents."""

import time

import httpx

from multiagent.llm.base import LLMResponse


class LlamaServerClient:
    """Thin wrapper around llama-server's native /completion endpoint.

    `use_chat_template` asks the server to wrap each prompt in the loaded model's own chat format
    (via /apply-template) before completing it. /completion otherwise sends raw text, which a
    chat-tuned model was never trained on; the server knows the right format, so nothing
    model-specific is hardcoded here.
    """

    def __init__(self, base_url: str, timeout: float = 120.0, use_chat_template: bool = False):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._use_chat_template = use_chat_template

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        json_schema: dict | None = None,
        client: httpx.Client | None = None,
    ) -> LLMResponse:
        started = time.monotonic()
        owns_client = client is None
        http_client = client or httpx.Client(timeout=self._timeout)
        try:
            if self._use_chat_template:
                prompt = self._apply_chat_template(http_client, prompt)
            payload: dict = {"prompt": prompt, "n_predict": max_tokens, "stream": False}
            if json_schema is not None:
                payload["json_schema"] = json_schema
            response = http_client.post(f"{self._base_url}/completion", json=payload)
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

    def _apply_chat_template(self, http_client: httpx.Client, prompt: str) -> str:
        """Raises on failure rather than quietly falling back to a raw prompt, which would change
        the model's behaviour without anyone noticing."""
        response = http_client.post(
            f"{self._base_url}/apply-template",
            json={"messages": [{"role": "user", "content": prompt}]},
        )
        response.raise_for_status()
        return response.json()["prompt"]
