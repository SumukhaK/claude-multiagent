"""Tests for the llama-server HTTP client. HTTP is mocked via httpx.MockTransport."""

import httpx

from multiagent.llm.llama_client import LlamaServerClient


def _client_with(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_generate_sends_prompt_and_max_tokens_to_completion_endpoint():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"content": "hi", "tokens_evaluated": 3, "tokens_predicted": 1})

    client = LlamaServerClient(base_url="http://127.0.0.1:8080")
    client.generate("hello", client=_client_with(handler))

    assert captured["url"].endswith("/completion")


def test_generate_parses_response_into_llm_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"content": "hello world", "tokens_evaluated": 5, "tokens_predicted": 2},
        )

    client = LlamaServerClient(base_url="http://127.0.0.1:8080")
    result = client.generate("hi", client=_client_with(handler))

    assert result.text == "hello world"
    assert result.prompt_tokens == 5
    assert result.completion_tokens == 2
    assert result.latency_seconds >= 0


def test_generate_raises_on_http_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = LlamaServerClient(base_url="http://127.0.0.1:8080")

    try:
        client.generate("hi", client=_client_with(handler))
        raised = False
    except httpx.HTTPStatusError:
        raised = True

    assert raised is True


def test_generate_sends_configured_max_tokens_as_n_predict():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"content": "", "tokens_evaluated": 0, "tokens_predicted": 0})

    client = LlamaServerClient(base_url="http://127.0.0.1:8080")
    client.generate("hi", max_tokens=64, client=_client_with(handler))

    assert captured["payload"]["n_predict"] == 64
    assert captured["payload"]["prompt"] == "hi"
    assert captured["payload"]["stream"] is False


def _capture_payload(**generate_kwargs) -> dict:
    import json

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"content": "", "tokens_evaluated": 0, "tokens_predicted": 0})

    LlamaServerClient(base_url="http://127.0.0.1:8080").generate(
        "hi", client=_client_with(handler), **generate_kwargs
    )
    return captured["payload"]


def test_generate_forwards_a_json_schema_so_the_server_constrains_decoding():
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}

    assert _capture_payload(json_schema=schema)["json_schema"] == schema


def test_generate_sends_no_json_schema_field_by_default():
    assert "json_schema" not in _capture_payload()


def _recording_handler(calls: list):
    """Answers /apply-template with a templated prompt and /completion with an empty completion."""
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "<U>" + body["messages"][0]["content"] + "<A>"})
        return httpx.Response(200, json={"content": "ok", "tokens_evaluated": 1, "tokens_predicted": 1})

    return handler


def test_with_chat_template_the_prompt_is_templated_by_the_server_before_completion():
    """The reasoning model is trained on its chat format; the server knows it, so ask the server."""
    calls = []
    client = LlamaServerClient(base_url="http://127.0.0.1:8080", use_chat_template=True)

    result = client.generate("hello", client=_client_with(_recording_handler(calls)))

    assert [path for path, _ in calls] == ["/apply-template", "/completion"]
    assert calls[0][1] == {"messages": [{"role": "user", "content": "hello"}]}
    assert calls[1][1]["prompt"] == "<U>hello<A>"
    assert result.text == "ok"


def test_without_chat_template_the_prompt_is_sent_raw_and_no_template_call_is_made():
    calls = []
    client = LlamaServerClient(base_url="http://127.0.0.1:8080")

    client.generate("hello", client=_client_with(_recording_handler(calls)))

    assert [path for path, _ in calls] == ["/completion"]
    assert calls[0][1]["prompt"] == "hello"


def test_chat_template_and_json_schema_combine():
    calls = []
    client = LlamaServerClient(base_url="http://127.0.0.1:8080", use_chat_template=True)

    client.generate("hi", json_schema={"type": "object"}, client=_client_with(_recording_handler(calls)))

    assert calls[1][1]["prompt"] == "<U>hi<A>"
    assert calls[1][1]["json_schema"] == {"type": "object"}


def test_a_failing_template_request_raises_instead_of_silently_sending_a_raw_prompt():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(501, json={"error": "no template"})

    client = LlamaServerClient(base_url="http://127.0.0.1:8080", use_chat_template=True)

    try:
        client.generate("hi", client=_client_with(handler))
        raised = False
    except httpx.HTTPStatusError:
        raised = True

    assert raised is True
