"""Tests for the single-source-of-truth settings module."""

from config.settings import Settings, get_settings


def test_defaults_match_documented_hardware_allocation():
    settings = Settings(_env_file=None)

    assert settings.llama_gpu_layers == 999
    assert settings.llama_flash_attn is True
    assert settings.llama_kv_cache_type == "q8_0"
    assert settings.ollama_tool_use_gpu is False
    assert settings.max_orchestrator_steps == 25
    assert settings.max_retries_per_step == 2


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("LLAMA_SERVER_PORT", "9000")
    monkeypatch.setenv("OTEL_ENABLED", "false")

    settings = Settings(_env_file=None)

    assert settings.llama_server_port == 9000
    assert settings.otel_enabled is False


def test_get_settings_returns_a_settings_instance():
    assert isinstance(get_settings(), Settings)
