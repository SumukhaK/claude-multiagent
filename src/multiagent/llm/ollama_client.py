"""HTTP client for Ollama, the backend the Planner, Coder and Tool agent run on. `use_gpu=False`
forces CPU-only inference; `use_gpu=True` lets Ollama split a model too big for the laptop's 4GB of
VRAM between GPU and CPU.
"""

import time

import httpx

from config.settings import Settings
from multiagent.llm.base import LLMResponse


class OllamaClient:
    """Thin wrapper around Ollama's /api/generate endpoint."""

    def __init__(
        self,
        host: str,
        model: str,
        use_gpu: bool = False,
        context_size: int | None = None,
        timeout: float = 120.0,
    ):
        self._host = host.rstrip("/")
        self._model = model
        self._use_gpu = use_gpu
        self._context_size = context_size
        self._timeout = timeout

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        json_schema: dict | None = None,
        client: httpx.Client | None = None,
    ) -> LLMResponse:
        started = time.monotonic()
        options: dict[str, int] = {
            "num_predict": max_tokens,
            "num_gpu": 0 if not self._use_gpu else -1,
        }
        if self._context_size is not None:
            options["num_ctx"] = self._context_size

        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
        if json_schema is not None:
            payload["format"] = json_schema

        owns_client = client is None
        http_client = client or httpx.Client(timeout=self._timeout)
        try:
            response = http_client.post(
                f"{self._host}/api/generate",
                json=payload,
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


def agent_client_from_settings(
    settings: Settings,
    model: str | None = None,
    context_size: int | None = None,
    timeout: float | None = None,
) -> OllamaClient:
    """The one Ollama client shared by the Planner, Coder and Tool agent, built from settings.

    Sharing one client (same model, same GPU/context options) keeps Ollama from reloading the model
    every time the agents alternate. Arguments override the settings for a single run.
    """
    return OllamaClient(
        host=settings.ollama_host,
        model=model or settings.ollama_agent_model,
        use_gpu=settings.ollama_agent_use_gpu,
        context_size=context_size or settings.ollama_agent_context_size,
        timeout=timeout or settings.ollama_agent_timeout,
    )
