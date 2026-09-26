"""Manual smoke test + micro-benchmark for Phase 1's local model serving.

Not a pytest suite — this touches real hardware (GPU, the actual llama-server.exe binary and
gguf file, a running Ollama service) and is meant to be read by a human. Run it directly:

    uv run python scripts/benchmark_llm.py

It starts the tuned llama-server (GPU-offloaded, flash-attn, quantized KV cache, continuous
batching), sends a few prompts through it while sampling VRAM usage, stops it, then does the
same for the Ollama tool-agent model forced onto the CPU — so you can see, on this exact
hardware, that the GPU allocation lands where REQUIREMENTS.md says it should and that the CPU
path never touches the GPU.
"""

import subprocess
import time

from config.settings import get_settings
from multiagent.llm.llama_client import LlamaServerClient
from multiagent.llm.llama_server import LlamaServerProcess
from multiagent.llm.ollama_client import OllamaClient

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


def benchmark_llama_server() -> None:
    settings = get_settings()
    print("\n=== llama-server (Planner/Coder model, GPU-offloaded) ===")
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
            result = client.generate(prompt, max_tokens=128)
            tok_per_sec = result.completion_tokens / result.latency_seconds if result.latency_seconds else 0
            print(
                f"- prompt_tokens={result.prompt_tokens} "
                f"completion_tokens={result.completion_tokens} "
                f"latency={result.latency_seconds:.2f}s "
                f"tok/s={tok_per_sec:.1f}"
            )
    finally:
        server.stop()
        print(f"GPU memory after stop: {gpu_memory_used_mib()}")


def benchmark_ollama_cpu_only() -> None:
    settings = get_settings()
    print("\n=== Ollama (Tool agent model, CPU-only) ===")
    print(f"GPU memory before call: {gpu_memory_used_mib()}")

    client = OllamaClient(
        host=settings.ollama_host,
        model=settings.ollama_tool_model,
        use_gpu=settings.ollama_tool_use_gpu,
    )
    result = client.generate(PROMPTS[0], max_tokens=128)
    tok_per_sec = result.completion_tokens / result.latency_seconds if result.latency_seconds else 0
    print(
        f"- prompt_tokens={result.prompt_tokens} "
        f"completion_tokens={result.completion_tokens} "
        f"latency={result.latency_seconds:.2f}s "
        f"tok/s={tok_per_sec:.1f}"
    )
    print(f"GPU memory after call: {gpu_memory_used_mib()}")


if __name__ == "__main__":
    benchmark_llama_server()
    benchmark_ollama_cpu_only()
