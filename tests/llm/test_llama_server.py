"""Tests for the llama-server launch command and process lifecycle wrapper.

These are unit tests: subprocess and HTTP calls are mocked, so they run without llama-server.exe
or a GPU present. Real hardware verification happens via scripts/benchmark_llm.py.
"""

import subprocess

import httpx
import pytest

from config.settings import Settings
from multiagent.llm.llama_server import LlamaServerProcess, build_llama_server_command


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        llama_cpp_dir=r"E:\LLMCPP",
        llama_model_path=r"E:\LLMCPP\model.gguf",
        llama_server_host="127.0.0.1",
        llama_server_port=8080,
        llama_gpu_layers=999,
        llama_context_size=8192,
        llama_parallel_slots=2,
        llama_flash_attn=True,
        llama_kv_cache_type="q8_0",
        llama_threads=6,
    )


def test_build_command_includes_gpu_offload_and_model_path(settings):
    command = build_llama_server_command(settings)

    assert command[0].endswith("llama-server.exe")
    assert "-m" in command and command[command.index("-m") + 1] == settings.llama_model_path
    assert "-ngl" in command and command[command.index("-ngl") + 1] == "999"


def test_build_command_enables_flash_attention_and_quantized_kv_cache(settings):
    command = build_llama_server_command(settings)

    assert command[command.index("-fa") + 1] == "on"
    assert command[command.index("-ctk") + 1] == "q8_0"
    assert command[command.index("-ctv") + 1] == "q8_0"


def test_build_command_disables_flash_attention_when_configured_off(settings):
    settings.llama_flash_attn = False
    command = build_llama_server_command(settings)

    assert command[command.index("-fa") + 1] == "off"


def test_build_command_enables_continuous_batching_and_parallel_slots(settings):
    command = build_llama_server_command(settings)

    assert "-cb" in command
    assert command[command.index("-np") + 1] == "2"


def test_build_command_sets_host_port_and_thread_cap(settings):
    command = build_llama_server_command(settings)

    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8080"
    assert command[command.index("-t") + 1] == "6"


def test_base_url_reflects_configured_host_and_port(settings):
    process = LlamaServerProcess(settings)

    assert process.base_url == "http://127.0.0.1:8080"


def test_start_launches_subprocess_with_the_built_command(settings, monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")

        class FakeProcess:
            def poll(self_inner):
                return None

        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = LlamaServerProcess(settings)
    process.start()

    assert captured["command"] == build_llama_server_command(settings)
    assert captured["cwd"] == settings.llama_cpp_dir
    assert process.is_running() is True


def test_start_is_a_no_op_when_already_running(settings, monkeypatch):
    call_count = {"count": 0}

    def fake_popen(command, **kwargs):
        call_count["count"] += 1

        class FakeProcess:
            def poll(self_inner):
                return None

        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = LlamaServerProcess(settings)
    process.start()
    process.start()

    assert call_count["count"] == 1


def test_wait_until_healthy_returns_once_health_endpoint_is_ok(settings, monkeypatch):
    responses = [httpx.ConnectError("not up yet"), httpx.Response(200)]

    def fake_get(url, timeout):
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    process = LlamaServerProcess(settings)
    process.wait_until_healthy(timeout=5.0, poll_interval=0.01)


def test_wait_until_healthy_times_out_if_never_healthy(settings, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout: (_ for _ in ()).throw(httpx.ConnectError("down")))
    monkeypatch.setattr("time.monotonic", _fake_clock())
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    process = LlamaServerProcess(settings)
    with pytest.raises(TimeoutError):
        process.wait_until_healthy(timeout=0.05, poll_interval=0.01)


def _fake_clock():
    state = {"t": 0.0}

    def clock():
        state["t"] += 0.02
        return state["t"]

    return clock


def test_stop_terminates_a_running_process(settings, monkeypatch):
    terminated = {"called": False}

    class FakeProcess:
        def poll(self_inner):
            return None if not terminated["called"] else 0

        def terminate(self_inner):
            terminated["called"] = True

        def wait(self_inner, timeout=None):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProcess())

    process = LlamaServerProcess(settings)
    process.start()
    process.stop()

    assert terminated["called"] is True
    assert process.is_running() is False


def test_stop_is_a_no_op_when_never_started(settings):
    process = LlamaServerProcess(settings)
    process.stop()  # must not raise


def test_start_sends_server_output_to_a_log_file_not_an_unread_pipe(settings, tmp_path, monkeypatch):
    """An unread stdout=PIPE fills its OS buffer after enough request logging and then blocks the
    server on its next log write, silently freezing every completion (found in a real eval run)."""
    log_path = tmp_path / "logs" / "llama-server.log"
    settings = settings.model_copy(update={"llama_log_path": str(log_path)})
    captured = {}

    def fake_popen(command, **kwargs):
        captured.update(kwargs)

        class FakeProcess:
            def poll(self_inner):
                return None

        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    LlamaServerProcess(settings).start()

    assert captured["stdout"] is not subprocess.PIPE
    assert captured["stderr"] == subprocess.STDOUT
    captured["stdout"].write("a log line\n")
    captured["stdout"].flush()
    assert log_path.read_text(encoding="utf-8") == "a log line\n"


def test_stop_closes_the_log_file(settings, tmp_path, monkeypatch):
    settings = settings.model_copy(update={"llama_log_path": str(tmp_path / "server.log")})
    captured = {}

    class FakeProcess:
        def poll(self_inner):
            return None

        def terminate(self_inner):
            pass

        def wait(self_inner, timeout=None):
            return 0

    def fake_popen(command, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    process = LlamaServerProcess(settings)
    process.start()
    process.stop()

    assert captured["stdout"].closed is True
