"""Tests for the Ollama HTTP client used by the Tool agent. HTTP is mocked."""

import json

import httpx

from multiagent.llm.ollama_client import OllamaClient


def _client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_generate_forces_cpu_only_by_setting_num_gpu_zero():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok", "prompt_eval_count": 1, "eval_count": 1})

    client = OllamaClient(host="http://127.0.0.1:11434", model="qwen2.5:7b-instruct", use_gpu=False)
    client.generate("hi", client=_client_with(handler))

    assert captured["payload"]["options"]["num_gpu"] == 0
    assert captured["payload"]["model"] == "qwen2.5:7b-instruct"
    assert captured["payload"]["stream"] is False


def test_generate_leaves_gpu_selection_to_ollama_when_use_gpu_is_true():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok", "prompt_eval_count": 1, "eval_count": 1})

    client = OllamaClient(host="http://127.0.0.1:11434", model="qwen2.5:7b-instruct", use_gpu=True)
    client.generate("hi", client=_client_with(handler))

    assert captured["payload"]["options"]["num_gpu"] == -1


def test_generate_parses_response_into_llm_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": "hello", "prompt_eval_count": 4, "eval_count": 2},
        )

    client = OllamaClient(host="http://127.0.0.1:11434", model="qwen2.5:7b-instruct", use_gpu=False)
    result = client.generate("hi", client=_client_with(handler))

    assert result.text == "hello"
    assert result.prompt_tokens == 4
    assert result.completion_tokens == 2
    assert result.latency_seconds >= 0


def test_generate_omits_num_ctx_by_default():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "", "prompt_eval_count": 0, "eval_count": 0})

    client = OllamaClient(host="http://127.0.0.1:11434", model="qwen2.5:7b-instruct", use_gpu=False)
    client.generate("hi", client=_client_with(handler))

    assert "num_ctx" not in captured["payload"]["options"]


def test_generate_sets_num_ctx_when_context_size_is_configured():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "", "prompt_eval_count": 0, "eval_count": 0})

    client = OllamaClient(
        host="http://127.0.0.1:11434", model="qwen2.5:7b-instruct", use_gpu=False, context_size=4096
    )
    client.generate("hi", client=_client_with(handler))

    assert captured["payload"]["options"]["num_ctx"] == 4096


def test_generate_hits_the_api_generate_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"response": "", "prompt_eval_count": 0, "eval_count": 0})

    client = OllamaClient(host="http://127.0.0.1:11434", model="qwen2.5:7b-instruct", use_gpu=False)
    client.generate("hi", client=_client_with(handler))

    assert captured["url"].endswith("/api/generate")


def test_generate_forwards_a_json_schema_as_ollamas_format_field():
    captured = {}
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "{}", "prompt_eval_count": 1, "eval_count": 1})

    client = OllamaClient(host="http://127.0.0.1:11434", model="m", use_gpu=False)
    client.generate("hi", json_schema=schema, client=_client_with(handler))

    assert captured["payload"]["format"] == schema


def _payload_sent_by(client) -> dict:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"response": "ok", "prompt_eval_count": 1, "eval_count": 1})

    client.generate("hi", client=_client_with(handler))
    return captured["payload"]


def test_agent_client_from_settings_uses_the_shared_agent_model_context_and_gpu_split():
    from config.settings import Settings
    from multiagent.llm.ollama_client import agent_client_from_settings

    settings = Settings(_env_file=None, ollama_agent_model="m:1b", ollama_agent_context_size=6000)

    payload = _payload_sent_by(agent_client_from_settings(settings))

    assert payload["model"] == "m:1b"
    assert payload["options"]["num_ctx"] == 6000
    assert payload["options"]["num_gpu"] == -1  # let Ollama split the model between GPU and CPU


def test_agent_client_from_settings_can_be_overridden_per_call():
    from config.settings import Settings
    from multiagent.llm.ollama_client import agent_client_from_settings

    client = agent_client_from_settings(
        Settings(_env_file=None), model="other:7b", context_size=2048, timeout=30.0
    )

    payload = _payload_sent_by(client)
    assert payload["model"] == "other:7b"
    assert payload["options"]["num_ctx"] == 2048
    assert client._timeout == 30.0
