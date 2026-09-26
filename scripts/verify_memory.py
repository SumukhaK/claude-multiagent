"""Manual smoke test for Phase 8's local memory layer against the real Ollama embedder.

Not part of pytest -- it needs a running Ollama with `nomic-embed-text` pulled. Run:

    uv run python scripts/verify_memory.py

Stores a few memories across two projects in a throwaway directory, then checks that recall is
relevant, scoped to the right project, capped, and that the embedder didn't grab GPU memory
that the llama-server needs (REQUIREMENTS.md §3).
"""

import subprocess
import tempfile
import time

from config.settings import get_settings
from multiagent.memory.store import build_mem0_store


def gpu_memory_used_mib() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return f"{result.stdout.strip()} MiB"
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return f"unavailable ({exc})"


def main() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        settings = get_settings().model_copy(update={"memory_path": tmp})
        print(f"GPU memory before: {gpu_memory_used_mib()}")

        proj = build_mem0_store(settings, project_id="proj-a")
        other = proj.for_project("proj-b")

        started = time.monotonic()
        proj.remember("This project uses FastAPI and pytest; tests live under tests/", kind="decision")
        proj.remember("Step 1 added GET /health returning {'status': 'ok'}", kind="step_summary")
        proj.remember("Database is SQLite in development", kind="decision")
        other.remember("Unrelated project: the user prefers Django", kind="decision")
        print(f"stored 4 memories in {time.monotonic() - started:.2f}s")
        print(f"GPU memory after embedding: {gpu_memory_used_mib()}")

        for query in ("which web framework do we use?", "what does the health endpoint return?"):
            started = time.monotonic()
            hits = proj.recall(query)
            print(f"\nQ: {query}  ({time.monotonic() - started:.2f}s)")
            for hit in hits:
                print(f"  - {hit}")

        print("\n=== recall_context (what would be injected into a prompt) ===")
        print(proj.recall_context("which web framework do we use?"))


if __name__ == "__main__":
    main()
