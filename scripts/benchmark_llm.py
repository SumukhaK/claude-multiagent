"""Manual smoke test + micro-benchmark for the local model serving.

Not a pytest suite: this touches real hardware (the GPU and a running Ollama service) and is meant
to be read by a human. Run it directly:

    uv run python scripts/benchmark_llm.py                 # the Ollama agent model (default)
    uv run python scripts/benchmark_llm.py --llama-server  # the optional llama.cpp backend

The Ollama benchmark sends a few prompts to the shared agent model and prints generation speed, how
Ollama split the model between GPU and CPU (`ollama ps`), and GPU memory before and after, so you
can see on this exact hardware what the model really costs. The llama-server benchmark starts the
tuned server (GPU-offloaded, flash-attn, quantized KV cache, continuous batching) and does the same.
"""

import argparse
import subprocess
import time

from config.settings import get_settings
from multiagent.llm.llama_client import LlamaServerClient
from multiagent.llm.llama_server import LlamaServerProcess
from multiagent.llm.ollama_client import agent_client_from_settings

PROMPTS = [
    "In one sentence, what does a Python list comprehension do?",
    "Write a one-line docstring for a function that reverses a string.",
    "Name one edge case to consider when parsing user-supplied file paths.",
]


def gpu_memory_used_mib() -> str:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return f"{result.stdout.strip()} MiB"
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return f"unavailable ({exc})"


def ollama_placement() -> str:
    """The model's size and GPU/CPU split as Ollama reports it, or why it is unavailable."""
    try:
        result = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10, check=True)
        return "\n".join(result.stdout.strip().splitlines())
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return f"unavailable ({exc})"


def print_result(result) -> None:
    tok_per_sec = result.completion_tokens / result.latency_seconds if result.latency_seconds else 0
    print(
        f"- prompt_tokens={result.prompt_tokens} completion_tokens={result.completion_tokens} "
        f"latency={result.latency_seconds:.2f}s tok/s={tok_per_sec:.1f}"
    )


def benchmark_ollama_agent_model() -> None:
    settings = get_settings()
    print(f"\n=== Ollama agent model: {settings.ollama_agent_model} (GPU/CPU split by Ollama) ===")
    print(f"GPU memory before: {gpu_memory_used_mib()}")
    client = agent_client_from_settings(settings)
    for prompt in PROMPTS:
        print_result(client.generate(prompt, max_tokens=128))
    print(f"GPU memory with the model loaded: {gpu_memory_used_mib()}")
    print("Ollama placement:\n" + ollama_placement())


def benchmark_llama_server() -> None:
    settings = get_settings()
    print("\n=== llama-server (optional backend, GPU-offloaded) ===")
    print(f"GPU memory before start: {gpu_memory_used_mib()}")

    server = LlamaServerProcess(settings)
    server.start()
    try:
        started = time.monotonic()
        server.wait_until_healthy(timeout=120.0)
        print(f"Server healthy after {time.monotonic() - started:.1f}s")
        print(f"GPU memory with model loaded: {gpu_memory_used_mib()}")

        client = LlamaServerClient(base_url=server.base_url)
        for prompt in PROMPTS:
            print_result(client.generate(prompt, max_tokens=128))
    finally:
        server.stop()
        print(f"GPU memory after stop: {gpu_memory_used_mib()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--llama-server", action="store_true", help="benchmark the optional llama.cpp backend")
    if parser.parse_args().llama_server:
        benchmark_llama_server()
    else:
        benchmark_ollama_agent_model()
