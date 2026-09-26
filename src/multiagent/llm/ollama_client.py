"""HTTP client for Ollama, used by the Tool agent. Forces CPU-only inference by default so it
never contends with the GPU-resident llama-server for the laptop's 4GB of VRAM.
"""

import time

import httpx

from multiagent.llm.base import LLMResponse


class OllamaClient:
    """Thin wrapper around Ollama's /api/generate endpoint."""

    def __init__(self, host: str, model: str, use_gpu: bool = False, timeout: float = 120.0):
        self._host = host.rstrip("/")
        self._model = model
        self._use_gpu = use_gpu
        self._timeout = timeout

    def generate(
        self, prompt: str, *, max_tokens: int = 512, client: httpx.Client | None = None
    ) -> LLMResponse:
        started = time.monotonic()
        owns_client = client is None
        http_client = client or httpx.Client(timeout=self._timeout)
        try:
            response = http_client.post(
                f"{self._host}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "num_gpu": 0 if not self._use_gpu else -1,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
        finally:
            if owns_client:
                http_client.close()
        elapsed = time.monotonic() - started
        return LLMResponse(
            text=data.get("response", ""),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            latency_seconds=elapsed,
        )
