"""Smoke tests for the wiring of the *real* agents (Planner, Coder, Tool, real git, real pytest),
driven by fake LLM clients. Catches a wrong constructor argument in seconds instead of an hour
into a real evaluation run.
"""

from functools import partial

from multiagent.evaluation.golden_tasks import GOLDEN_TASKS
from multiagent.evaluation.real_system import build_real_system
from multiagent.evaluation.runner import run_task
from multiagent.llm.base import LLMResponse

TASKS = {task.id: task for task in GOLDEN_TASKS}


class FakeLLM:
    def __init__(self, text):
        self._text = text
        self.prompts = []

    def generate(self, prompt, *, max_tokens=512):
        self.prompts.append(prompt)
        return LLMResponse(text=self._text, prompt_tokens=11, completion_tokens=7, latency_seconds=0.25)


def factory(llm):
    return partial(
        _build, llm=llm
    )


def _build(sandbox, meter, llm):
    return build_real_system(
        planner_llm=llm, coder_llm=llm, tool_llm=llm, sandbox=sandbox, meter=meter,
        max_retries=1, max_steps=8, max_tokens=64,
    )


def test_an_adversarial_task_is_refused_by_the_real_orchestrator_without_any_llm_call(tmp_path):
    llm = FakeLLM("unused")

    result = run_task(TASKS["adversarial_secret_request"], 0, factory(llm), tmp_path)

    assert result.outcome == "correctly_refused"
    assert llm.prompts == []


def test_a_model_that_returns_garbage_escalates_cleanly_through_the_real_agents(tmp_path):
    llm = FakeLLM("I am not going to give you JSON.")

    result = run_task(TASKS["feature_add"], 0, factory(llm), tmp_path)

    assert result.outcome == "escalated"
    assert result.error and "escalated" in result.error
    assert result.total_tokens > 0  # the real planner's LLM calls went through the meter
    assert result.had_failure_event is True
    assert "planner" in result.llm_latencies


def test_a_scripted_model_drives_the_real_stack_to_a_genuine_success(tmp_path):
    """Planner, Coder, reviewer and Tool agent are all the real classes; only the model text is
    scripted. Proves the whole pipeline (real files, real pytest, real git commit and push to the
    local remote) can succeed, so a failure in the real run is the model's, not the harness's."""
    import json

    plan = json.dumps({"kind": "plan", "goal": "add", "steps": [{"step_id": 1, "description": "add add()", "edge_cases": []}], "clarifying_questions": []})
    change = json.dumps({
        "kind": "code_change", "step_id": 1, "summary": "added add()",
        "test_files": [{"path": "test_calc.py", "content": "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"}],
        "implementation_files": [{"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"}],
    })
    review = json.dumps({"kind": "step_review", "step_id": 1, "approved": True, "feedback": "ok"})

    class Scripted:
        def generate(self, prompt, *, max_tokens=512):
            if "Planning agent, reviewing" in prompt:
                text = review
            elif "You are the Coding agent" in prompt:
                text = change
            elif "commit message" in prompt:
                text = "feat: add add()"
            else:
                text = plan
            return LLMResponse(text=text, prompt_tokens=10, completion_tokens=10, latency_seconds=0.1)

    result = run_task(TASKS["feature_add"], 0, factory(Scripted()), tmp_path)

    assert result.outcome == "success", result.error
    assert result.acceptance_passed is True
    assert {op for op, ok in result.tool_operations if ok} >= {"create_branch", "commit", "push"}


def test_constrain_json_sends_a_schema_to_the_planner_and_never_to_the_tool_agent(tmp_path):
    seen = {"planner": [], "tool": []}

    class Recording:
        def __init__(self, role):
            self._role = role

        def generate(self, prompt, *, max_tokens=512, json_schema=None):
            seen[self._role].append(json_schema)
            return LLMResponse(text="no json", prompt_tokens=1, completion_tokens=1, latency_seconds=0.1)

    def build(sandbox, meter):
        return build_real_system(
            planner_llm=Recording("planner"), coder_llm=Recording("planner"), tool_llm=Recording("tool"),
            sandbox=sandbox, meter=meter, max_retries=1, max_steps=6, max_tokens=64, constrain_json=True,
        )

    run_task(TASKS["feature_add"], 0, build, tmp_path)

    assert seen["planner"] and all(schema is not None for schema in seen["planner"])
    assert all(schema is None for schema in seen["tool"])


def test_with_a_tracer_every_layer_of_a_real_run_is_traced_and_failures_are_logged(tmp_path):
    import json

    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from multiagent.observability.tracing import FailureLog

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    failure_path = tmp_path / "failures.jsonl"

    def build(sandbox, meter):
        return build_real_system(
            planner_llm=FakeLLM("no json here"), coder_llm=FakeLLM("no json here"), tool_llm=FakeLLM("x"),
            sandbox=sandbox, meter=meter, max_retries=1, max_steps=6, max_tokens=64,
            tracer=provider.get_tracer("test"), failure_log=FailureLog(failure_path),
        )

    run_task(TASKS["feature_add"], 0, build, tmp_path / "work")

    names = {span.name for span in exporter.get_finished_spans()}
    assert {"orchestrator.run", "agent.planner.create_plan", "llm.planner.generate"} <= names
    failures = [json.loads(line) for line in failure_path.read_text().splitlines()]
    assert any(f["call"] == "agent.planner.create_plan" for f in failures)
    assert any("no complete JSON object" in f["error"] for f in failures)
