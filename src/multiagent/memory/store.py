"""Local memory layer: mem0 behind a small, project-scoped MemoryStore.

Fully local per CLAUDE.md §3/§5: embeddings come from Ollama (`nomic-embed-text`) and vectors
live in an on-disk qdrant store. No LLM is configured on purpose — memories are stored verbatim
(`infer=False`), so memory can never silently spend the tight model budget on fact extraction.

Memory is an enhancement, not a dependency of correctness: if the embedding backend is down,
`remember` and `recall` fail soft (logged, not raised) so a coding task isn't killed by it.
Recalled text is treated as data, never instructions (CLAUDE.md §4) — it is wrapped and scanned
with the same guardrail used for tool output, and capped so it can't blow the context budget.
"""

import logging
import os
from typing import Any, Protocol

from config.settings import Settings
from multiagent.guardrails.input_filter import (
    sanitize_tool_output,
    scan_tool_output_for_injection_markers,
)
from multiagent.guardrails.secret_scanner import scan_for_secrets

# mem0 reads this at import time and defaults to sending PostHog telemetry; this project is
# local-first, so it must be set before mem0 is ever imported (see build_mem0_store below).
os.environ.setdefault("MEM0_TELEMETRY", "False")

logger = logging.getLogger(__name__)


class Mem0Like(Protocol):
    def add(self, messages: str, *, user_id: str, infer: bool, metadata: dict[str, Any]) -> Any: ...
    def search(self, query: str, *, filters: dict[str, Any], top_k: int) -> dict[str, Any]: ...


def build_mem0_config(settings: Settings) -> dict[str, Any]:
    """mem0 config: Ollama embeddings + on-disk qdrant, deliberately with no LLM."""
    return {
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": settings.memory_embedding_model,
                "ollama_base_url": settings.ollama_host,
                "embedding_dims": settings.memory_embedding_dims,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "path": settings.memory_path,
                "collection_name": "multiagent",
                "embedding_model_dims": settings.memory_embedding_dims,
                "on_disk": True,
            },
        },
    }


class MemoryStore:
    """Remembers and recalls short text for one project, capped to protect the context budget."""

    def __init__(
        self, memory: Mem0Like, project_id: str, recall_limit: int, recall_max_chars: int
    ):
        self._memory = memory
        self._project_id = project_id
        self._recall_limit = recall_limit
        self._recall_max_chars = recall_max_chars

    def for_project(self, project_id: str) -> "MemoryStore":
        """A store for another project sharing this one's backend client. Local qdrant allows
        only one client per storage folder per process, so projects differ by scope, not client."""
        return MemoryStore(self._memory, project_id, self._recall_limit, self._recall_max_chars)

    def remember(self, text: str, kind: str) -> bool:
        """Store `text` verbatim under this project. Returns False if skipped or the backend failed."""
        if not text.strip():
            return False
        if kinds := scan_for_secrets(text):
            # Kinds only, never the value: a user can paste a key into a clarification answer, and
            # storing it would persist it on disk and recall it into future prompts.
            logger.warning("memory refused to store text containing a secret (%s)", ", ".join(kinds))
            return False
        try:
            self._memory.add(text, user_id=self._project_id, infer=False, metadata={"kind": kind})
        except Exception as exc:  # noqa: BLE001 - third-party backend with a wide exception surface; memory must fail soft
            logger.warning("memory remember failed: %s", exc)
            return False
        return True

    def recall(self, query: str) -> list[str]:
        """Most relevant memories for this project, best first. Empty if none or the backend failed."""
        try:
            response = self._memory.search(
                query, filters={"user_id": self._project_id}, top_k=self._recall_limit
            )
        except Exception as exc:  # noqa: BLE001 - see remember()
            logger.warning("memory recall failed: %s", exc)
            return []
        return [item["memory"] for item in response.get("results", [])]

    def recall_context(self, query: str) -> str:
        """Recalled memories as a size-capped, guardrail-wrapped block ready for a prompt, or ""."""
        lines: list[str] = []
        used = 0
        for memory in self.recall(query):
            memory = memory[: self._recall_max_chars]
            if used + len(memory) > self._recall_max_chars:
                break
            lines.append(f"- {memory}")
            used += len(memory)
        if not lines:
            return ""

        body = "\n".join(lines)
        markers = scan_tool_output_for_injection_markers(body)
        if markers:
            logger.warning("recalled memory contains injection-style phrasing: %s", ", ".join(markers))
        return sanitize_tool_output(body)


def build_mem0_store(settings: Settings, project_id: str) -> MemoryStore:
    """Build a real MemoryStore backed by local mem0. Imports mem0 lazily so telemetry is
    already disabled by the time it loads, and so unit tests never need it installed/running."""
    from mem0 import Memory

    return MemoryStore(
        Memory.from_config(build_mem0_config(settings)),
        project_id=project_id,
        recall_limit=settings.memory_recall_limit,
        recall_max_chars=settings.memory_recall_max_chars,
    )
