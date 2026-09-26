"""Builds the real Planner + Coder + Tool + orchestrator stack for one evaluation run.

Everything is real — the agent classes, the sandboxed filesystem and pytest runner, and real git
against a throwaway repo with a local bare remote — except the LLM clients, which are injected so
tests can drive this with fakes. Every LLM client, agent and tool is wrapped in metering; the agents
themselves are unchanged. Memory is deliberately off, so tasks are independent of each other.
"""

from pathlib import Path
from typing import Any

from opentelemetry.trace import Tracer

from multiagent.agents.coder.agent import CoderAgent
from multiagent.agents.planner.agent import PlannerAgent
from multiagent.agents.tool.agent import ToolAgent
from multiagent.evaluation.metering import Meter, MeteredAgent, MeteredLLMClient, MeteredTools
from multiagent.evaluation.sandbox import LocalEvalGitTools
from multiagent.llm.base import LLMClient
from multiagent.observability.tracing import FailureLog
from multiagent.observability.wrappers import TracedAgent, TracedLLMClient, TracedTools
from multiagent.orchestrator.orchestrator import Orchestrator
from multiagent.tools.hardware_test_runner import HardwareTestRunner
from multiagent.tools.pytest_runner import SandboxedPytestRunner
from multiagent.tools.writable_filesystem import WritableFilesystem


def build_real_system(
    *,
    planner_llm: LLMClient,
    coder_llm: LLMClient,
    tool_llm: LLMClient,
    sandbox: Path,
    meter: Meter,
    max_retries: int,
    max_steps: int,
    max_tokens: int,
    constrain_json: bool = False,
    tracer: Tracer | None = None,
    failure_log: FailureLog | None = None,
) -> Orchestrator:
    """With a `tracer`, every LLM call, agent call and git operation also becomes a span (nested
    under the orchestrator's per-run root span) and failures go to `failure_log`."""

    def llm(inner: LLMClient, role: str) -> LLMClient:
        metered = MeteredLLMClient(inner, meter, role)
        return TracedLLMClient(metered, tracer, role, failure_log) if tracer else metered

    def agent(inner: Any, name: str) -> Any:
        metered = MeteredAgent(inner, meter, name)
        return TracedAgent(metered, tracer, name, failure_log) if tracer else metered

    git_tools = MeteredTools(LocalEvalGitTools(sandbox), meter)
    planner = PlannerAgent(llm(planner_llm, "planner"), "eval", max_tokens=max_tokens, constrain_json=constrain_json)
    coder = CoderAgent(
        llm(coder_llm, "coder"),
        WritableFilesystem(sandbox),
        SandboxedPytestRunner(sandbox),
        "eval",
        max_tokens=max_tokens,
        constrain_json=constrain_json,
    )
    tool = ToolAgent(
        git_tools=TracedTools(git_tools, tracer, failure_log) if tracer else git_tools,
        llm_client=llm(tool_llm, "tool"),
        hardware_test_runner=HardwareTestRunner(),
        task_id="eval",
        max_retries=max_retries,
    )
    return Orchestrator(
        planner_agent=agent(planner, "planner"),
        coder_agent=agent(coder, "coder"),
        tool_agent=agent(tool, "tool"),
        max_retries_per_step=max_retries,
        max_orchestrator_steps=max_steps,
        tracer=tracer,
    )
