"""Builds the real Planner + Coder + Tool + orchestrator stack for one evaluation run.

Everything is real — the agent classes, the sandboxed filesystem and pytest runner, and real git
against a throwaway repo with a local bare remote — except the LLM clients, which are injected so
tests can drive this with fakes. Every LLM client, agent and tool is wrapped in metering; the agents
themselves are unchanged. Memory is deliberately off, so tasks are independent of each other.
"""

from pathlib import Path

from multiagent.agents.coder.agent import CoderAgent
from multiagent.agents.planner.agent import PlannerAgent
from multiagent.agents.tool.agent import ToolAgent
from multiagent.evaluation.metering import Meter, MeteredAgent, MeteredLLMClient, MeteredTools
from multiagent.evaluation.sandbox import LocalEvalGitTools
from multiagent.llm.base import LLMClient
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
) -> Orchestrator:
    planner = PlannerAgent(
        MeteredLLMClient(planner_llm, meter, "planner"),
        "eval",
        max_tokens=max_tokens,
        constrain_json=constrain_json,
    )
    coder = CoderAgent(
        MeteredLLMClient(coder_llm, meter, "coder"),
        WritableFilesystem(sandbox),
        SandboxedPytestRunner(sandbox),
        "eval",
        max_tokens=max_tokens,
        constrain_json=constrain_json,
    )
    tool = ToolAgent(
        git_tools=MeteredTools(LocalEvalGitTools(sandbox), meter),
        llm_client=MeteredLLMClient(tool_llm, meter, "tool"),
        hardware_test_runner=HardwareTestRunner(),
        task_id="eval",
        max_retries=max_retries,
    )
    return Orchestrator(
        planner_agent=MeteredAgent(planner, meter, "planner"),
        coder_agent=MeteredAgent(coder, meter, "coder"),
        tool_agent=MeteredAgent(tool, meter, "tool"),
        max_retries_per_step=max_retries,
        max_orchestrator_steps=max_steps,
    )
