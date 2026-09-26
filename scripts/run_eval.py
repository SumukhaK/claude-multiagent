"""Run the golden evaluation against the real local models and publish the results.

    uv run python scripts/run_eval.py --repeats 2 --update-readme

Starts llama-server (Planner/Coder) and uses Ollama (Tool agent), runs every golden task
`--repeats` times in a throwaway git sandbox with a local bare remote (never GitHub), and writes
results incrementally to evals/results/<timestamp>.jsonl so an interrupted run keeps what it has.
It is slow (minutes per task on this hardware) and keeps the GPU/CPU busy: not for casual use.
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
from multiagent.llm.ollama_client import OllamaClient

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
        help="constrain Planner/Coder decoding to their JSON schemas (default: LLAMA_CONSTRAIN_JSON)",
    )
    parser.add_argument("--update-readme", action="store_true", help="publish the report into README.md")
    args = parser.parse_args()

    tasks = [t for t in GOLDEN_TASKS if not args.tasks or t.id in args.tasks]
    settings = get_settings()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl = out_dir / f"{stamp}.jsonl"
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

    server = LlamaServerProcess(settings)
    server.start()
    try:
        server.wait_until_healthy(timeout=120.0)
        llama = LlamaServerClient(base_url=server.base_url)
        ollama = OllamaClient(
            host=settings.ollama_host,
            model=settings.ollama_tool_model,
            use_gpu=settings.ollama_tool_use_gpu,
            context_size=settings.ollama_tool_context_size,
        )
        make_system = partial(
            _build,
            llama=llama,
            ollama=ollama,
            max_retries=settings.max_retries_per_step,
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            constrain_json=(
                settings.llama_constrain_json if args.constrain_json is None else args.constrain_json
            ),
        )
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workdir:
            results = run_suite(tasks, args.repeats, make_system, Path(workdir), on_result)
    finally:
        server.stop()

    report = aggregate(results)
    markdown = render_markdown(
        report,
        metadata={
            "date": datetime.now(UTC).strftime("%Y-%m-%d"),
            "model": Path(settings.llama_model_path).name,
            "repeats": args.repeats,
        },
    )
    (out_dir / f"{stamp}.md").write_text(markdown, encoding="utf-8")
    print("\n" + markdown)
    if args.update_readme:
        readme = ROOT / "README.md"
        readme.write_text(update_readme(readme.read_text(encoding="utf-8"), markdown), encoding="utf-8")
        print("README.md updated.")


def _build(sandbox, meter, *, llama, ollama, max_retries, max_steps, max_tokens, constrain_json):
    return build_real_system(
        planner_llm=llama, coder_llm=llama, tool_llm=ollama, sandbox=sandbox, meter=meter,
        max_retries=max_retries, max_steps=max_steps, max_tokens=max_tokens,
        constrain_json=constrain_json,
    )


if __name__ == "__main__":
    main()
