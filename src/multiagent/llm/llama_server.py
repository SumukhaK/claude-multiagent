"""Launch-command builder and process lifecycle for the local llama-server (llama.cpp).

Flags are matched against the specific llama-server.exe build in E:\\LLMCPP (checked via
`llama-server.exe --help` before writing this, since flag names change between llama.cpp
versions). See REQUIREMENTS.md for the reasoning behind each setting.
"""

import subprocess
import time
from pathlib import Path

import httpx

from config.settings import Settings


def build_llama_server_command(settings: Settings) -> list[str]:
    """Build the llama-server.exe argv for the current settings' hardware allocation."""
    exe = str(Path(settings.llama_cpp_dir) / "llama-server.exe")
    return [
        exe,
        "-m", settings.llama_model_path,
        "--host", settings.llama_server_host,
        "--port", str(settings.llama_server_port),
        "-ngl", str(settings.llama_gpu_layers),
        "-c", str(settings.llama_context_size),
        "-np", str(settings.llama_parallel_slots),
        "-cb",
        "-fa", "on" if settings.llama_flash_attn else "off",
        "-ctk", settings.llama_kv_cache_type,
        "-ctv", settings.llama_kv_cache_type,
        "-t", str(settings.llama_threads),
    ]


class LlamaServerProcess:
    """Starts, health-checks, and stops the local llama-server subprocess."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._process: subprocess.Popen | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self._settings.llama_server_host}:{self._settings.llama_server_port}"

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        """Launch llama-server if it isn't already running under this wrapper."""
        if self.is_running():
            return
        self._process = subprocess.Popen(
            build_llama_server_command(self._settings),
            cwd=self._settings.llama_cpp_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def wait_until_healthy(self, timeout: float = 60.0, poll_interval: float = 0.5) -> None:
        """Poll GET /health until it responds 200, or raise TimeoutError."""
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.base_url}/health", timeout=2.0)
                if response.status_code == 200:
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(poll_interval)
        raise TimeoutError(f"llama-server did not become healthy within {timeout}s") from last_error

    def stop(self, timeout: float = 10.0) -> None:
        """Terminate the server, escalating to kill if it doesn't exit in time."""
        if self._process is None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=timeout)
        self._process = None
