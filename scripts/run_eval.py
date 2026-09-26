"""Run the golden evaluation against the real local model and record the results.

    uv run python scripts/run_eval.py --repeats 2

By default the Planner, Coder and Tool agent all run on the Ollama model in settings
(OLLAMA_AGENT_MODEL, `qwen2.5:7b-instruct`), through ONE shared client. The optional llama.cpp
backend is still available with `--llama-server`. Every golden task runs `--repeats` times in a
throwaway git sandbox with a local bare remote (never GitHub); results are written incrementally to
evals/results/<timestamp>.jsonl so an interrupted run keeps what it has, and every run that does
not succeed keeps its evidence under evals/artifacts/<timestamp>/.

It is slow (minutes per task on this hardware) and keeps the CPU and GPU busy: not for casual use.
"""

import argparse
import json
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from config.settings import get_settings
from multiagent.evaluation.golden_tasks import GOLDEN_TASKS
from multiagent.evaluation.real_system import build_real_system
from multiagent.evaluation.report import aggregate, render_markdown, update_readme
from multiagent.evaluation.runner import RunResult, run_suite
from multiagent.llm.llama_client import LlamaServerClient
from multiagent.llm.llama_server import LlamaServerProcess
from multiagent.llm.ollama_client import agent_client_from_settings
from multiagent.observability.tracing import FailureLog, configure_tracing, get_tracer

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeats", type=int, default=2, help="runs per task (default 2)")
    parser.add_argument("--tasks", nargs="*", help="only these task ids")
    parser.add_argument("--max-steps", type=int, default=12, help="orchestrator step budget per run")
    parser.add_argument("--max-tokens", type=int, default=1200, help="max tokens per Planner/Coder response")
    parser.add_argument(
        "--constrain-json",
        action="store_true",
        default=None,
        help="constrain Planner/Coder decoding to their JSON schemas (default: CONSTRAIN_JSON)",
    )
    parser.add_argument("--agent-model", help="Ollama model for all agents (default: OLLAMA_AGENT_MODEL)")
    parser.add_argument("--agent-context", type=int, help="context size (default: OLLAMA_AGENT_CONTEXT_SIZE)")
    parser.add_argument("--agent-timeout", type=float, help="seconds per call (default: OLLAMA_AGENT_TIMEOUT)")
    parser.add_argument(
        "--llama-server",
        action="store_true",
        help="use the optional llama.cpp backend for the Planner and Coder (Tool agent stays on Ollama)",
    )
    parser.add_argument(
        "--chat-template",
        action="store_true",
        default=None,
        help="with --llama-server: wrap prompts in the model's chat template (default: LLAMA_USE_CHAT_TEMPLATE)",
    )
    parser.add_argument("--update-readme", action="store_true", help="also publish the report into README.md")
    args = parser.parse_args()
    if args.llama_server and args.agent_model:
        parser.error("--agent-model applies to the Ollama backend, not --llama-server")
    if args.chat_template and not args.llama_server:
        parser.error("--chat-template only applies with --llama-server (Ollama applies its own template)")

    tasks = [t for t in GOLDEN_TASKS if not args.tasks or t.id in args.tasks]
    settings = get_settings()
    configure_tracing(settings)  # spans to OTEL_TRACE_PATH, failures to FAILURE_LOG_PATH
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / f"{stamp}.jsonl"
    artifacts_dir = ROOT / "evals" / "artifacts" / stamp  # evidence of every run that did not succeed
    total = len(tasks) * args.repeats
    done = 0

    def on_result(result: RunResult) -> None:
        nonlocal done
        done += 1
        with jsonl.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(result)) + "\n")
        print(
            f"[{done}/{total}] {result.task_id}#{result.repeat}: {result.outcome} "
            f"({result.wall_seconds:.0f}s, {result.total_tokens} tokens)",
            flush=True,
        )

    server = None
    try:
        if args.llama_server:
            server = LlamaServerProcess(settings)
            server.start()
            server.wait_until_healthy(timeout=120.0)
            use_template = settings.llama_use_chat_template if args.chat_template is None else args.chat_template
            planner_coder_llm = LlamaServerClient(base_url=server.base_url, use_chat_template=use_template)
            tool_llm = agent_client_from_settings(settings)
            model_name = Path(settings.llama_model_path).name
        else:
            # One shared client for all three agents: different options per agent would make Ollama
            # reload the whole model every time the agents alternate.
            planner_coder_llm = tool_llm = agent_client_from_settings(
                settings, model=args.agent_model, context_size=args.agent_context, timeout=args.agent_timeout
            )
            model_name = args.agent_model or settings.ollama_agent_model
        make_system = partial(
            _build,
            planner_coder_llm=planner_coder_llm,
            tool_llm=tool_llm,
            max_retries=settings.max_retries_per_step,
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            tracer=get_tracer(),
            failure_log=FailureLog(Path(settings.failure_log_path)),
            constrain_json=settings.constrain_json if args.constrain_json is None else args.constrain_json,
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
            results = run_suite(tasks, args.repeats, make_system, Path(workdir), on_result, artifacts_dir)
    finally:
        if server is not None:
            server.stop()

    report = aggregate(results)
    markdown = render_markdown(
        report,
        metadata={
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "model": model_name,
            "repeats": args.repeats,
        },
    )
    (out_dir / f"{stamp}.md").write_text(markdown, encoding="utf-8")
    print("\n" + markdown)
    print(f"Failure artifacts (local, gitignored): {artifacts_dir}")
    if args.update_readme:
        readme = ROOT / "README.md"
        readme.write_text(update_readme(readme.read_text(encoding="utf-8"), markdown), encoding="utf-8")
        print("README.md updated.")


def _build(sandbox, meter, *, planner_coder_llm, tool_llm, max_retries, max_steps, max_tokens, constrain_json, tracer, failure_log):
    return build_real_system(
        planner_llm=planner_coder_llm, coder_llm=planner_coder_llm, tool_llm=tool_llm, sandbox=sandbox, meter=meter,
        max_retries=max_retries, max_steps=max_steps, max_tokens=max_tokens,
        constrain_json=constrain_json, tracer=tracer, failure_log=failure_log,
    )


if __name__ == "__main__":
    main()
