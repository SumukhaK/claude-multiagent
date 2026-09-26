"""Tests for the single-source-of-truth settings module."""

from config.settings import Settings, get_settings


def test_defaults_match_documented_hardware_allocation():
    settings = Settings(_env_file=None)

    assert settings.llama_gpu_layers == 999
    assert settings.llama_flash_attn is True
    assert settings.llama_kv_cache_type == "q8_0"
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


def test_agents_default_to_one_shared_ollama_model_split_between_gpu_and_cpu():
    """Planner, Coder and Tool agent share one model (a second set of options would make Ollama
    reload the whole model each time the agents alternate); a 7B model does not fit 4GB of VRAM."""
    settings = Settings(_env_file=None)

    assert settings.ollama_agent_model == "qwen2.5:7b-instruct"
    assert settings.ollama_agent_use_gpu is True
    assert settings.ollama_agent_context_size == 8192
    assert settings.ollama_agent_timeout >= 600  # ~8 tokens/s: a long reply takes minutes


def test_the_per_agent_tool_model_settings_are_gone():
    settings = Settings(_env_file=None)

    assert not hasattr(settings, "ollama_tool_model")
    assert not hasattr(settings, "ollama_tool_use_gpu")
    assert not hasattr(settings, "ollama_tool_context_size")


def test_json_constraint_is_backend_neutral_and_off_by_default():
    settings = Settings(_env_file=None)

    assert settings.constrain_json is False
    assert not hasattr(settings, "llama_constrain_json")
