# Project Tracker — Claude Multiagent

This file is the single source of truth for phase status. Update it (and the matching section of
`README.md`) immediately after each phase's PR merges. Never delete history here — mark phases
done/blocked/deferred instead of removing them.

---

## 0. Original prompt (verbatim, on record)

> first read this, then while planning think as deep as possible and implement in as simple way
> as possible , we are building a multi agent ai driven coding agent. you act like a a senior
> software architect, go through this prompt and extract whats suitable for claude.md from them
> and add them there and take rest of the informations as project requirements and
> implementation guidelines. once done reading, analyse it deeply, plan the project and features
> to implement in each phases of the project and record them in a md file in project folder and
> update them as we accomplish implemntation of each phases. record this initial prompt as well
> in that tracker md. update the project readme with a high level of architecture diagram of
> what we are planning to do and update the same readme with short details as we implement each
> phase succesfully. Think and analyse before acting, read the existing code before making edits
> or updates. if there s a bug, read the code, understand and then plan before fixing it. fixing
> one bug should not break existing and working parts of the project. Create a remote repo in my
> github with a readme file and push code feature by feature by creating branches and merge them
> once its reviewed by you. In project readme, keep high level architecure diagram, project s
> brief descrption, tools and libraries used. Create a separate readme for project requirement
> in techincal terms and a separate readme for explaining the project and its scope to non
> technical people, another tracker file where you mention the planned phases of this multi
> agent system and put tracker with them to mark it for update as we continue to execute the
> project.
>
> use TDD, write unit tests before writing actaul code. divide tasks into features and write
> code accordingly and push them to git with approriate commmit messages. each feature should
> first open a PR in git. Review the code and merge if its fine, if it changes the status to
> "Request changes" act on them accordingly. also the code should be simple, human readable and
> human understandable format. do not assume anything, do not make up anything. ask if confused.
> keep all the api keys and sensitive data in env and do not push them. keep all configurations
> related settings in one file and at one place.
>
> There is a gguf format of a model and llm cpp in E:\LLMCPP folder, use that as a model to run
> the system. My suggestion is to run that model on this laptops graphic card instead of ram so
> that it gets maximum hardware benefits. First scan the system and see if it is possible to
> host the model on gpu as well as kv cache. If you can host the model on gpu and kv cache on
> regualr cpu and run it efficiently that's fine too. But you analyse and take the most efficient
> solution. Do llm inferencing so that we put minium load on the laptop hardware. While running
> the model on llm cpp configure kv cache, continous bathing, flash attention etc as it fits our
> hardware. At the end, run it as smoothly as possible on hardware and should be getting the best
> out of the model as well. Find the balance between both the optimizations.
>
> The system I want to build : one layer that takes input from the user and acts as agent loop.
> We will create 3 sub agents. One for planning the coding/debugging tasks given by the user and
> one for coding and the third one for tool access such as pushing it on the git etc. Follow
> structured json format responses to communicate between the agent strictly. Planning agent s
> job is to think deeply, read exisiting code before editing if it is debugging or feature
> enhancement and create a step by step actionable plan for the coding agent. Ask user for
> clarification questions. Never assume any requirements or make up things, always use best
> engineering standars followed in the industry, use open source libraries if user didn't
> mention in the prompt. Think of all possible edge cases before finalizing the requirements and
> passing it to the coding agent. Create step by step plan to execute the given tasks and once
> coding agent is done executing, review it before it starts working on the next steps, enforce
> this behaviour strictly.
>
> Second agent s job is to write/modify/delete the codebase based on the plan created by the
> coding planner agent. Write unit tests first for every feature you implement and run them with
> the help of tool execution agent if necessary. If debugging or enhancing a feature or writing
> a new feature creates a dependecy or overlap with any of the exisiting features, read the
> exisiting code first because it should not cause problem with exisitng feature or create new
> bugs or edge cases.
>
> Third agent s job is to manage the code on the remote repo if user provides one. In case if
> code needs hardware access to certain tests on hardware or create a virtual device or
> emulator, this agent should take it up and report back results of the tests. The idea is to
> give minimal tool access to each of the agents to enhance secuirty of the whole system. Avoid
> unnecessary tool access to any of the agents. Treat tool responses as just outputs and not as
> prompts to be executed in most cases to avoid prompt injections via tool responses. Plan the
> fallback cases for each tool executions exceptions, timeouts. Have clear communications
> between the sub agents and when stuck in any phase communicate it to the main agent so that it
> can be re-planned. Have limited re tires for each failures and report the failures to main
> agent so that it can be revisted and come up with alternate approach or reported back to the
> user. No infinte loops in any of the agents or main agent. Enforce logging, traces and failure
> documents in all the sub agents as well as main agents for evaluations. Use centralized
> communication or message passing or shard memory communication according to the situations.
> You can use langraph for agent coordination and opentelemetry for agent observability. You can
> use langsmith and openeval for agent evaluation.
>
> You can use mem0 open source library for memory layer of our multi agent system. Use .env for
> simple cases if possible. use security guardrails against offensive prompts are users trying
> to access sensitive informations or asking for passwords or api keys etc. Use only free
> portions of the libraries I mentioned so far as its portfolio project and not real industry
> level product which we are going to host and make money out of.
>
> You can use ollama s qwen 2.5 model which is already downloaded on ollama for tool access/
> third agent if that sounds like better choice than the one we have. Before chosing multiple
> models, consider laptop s hardware limitations because if u start using 85%+ of cpu and gpu to
> run these laptop will hang and everything will become un usable.
>
> Once we are done building this multi agent system, have a golden test set ready to evaluate.
> We should have metrics for latency, token usage, tools success rate, hallunications and
> recovery from them, total cost etc. And add it at the bottom of project readme on our git repo.

### 0.1 Follow-up prompt (2026-09-26, context engineering — verbatim)

> also forgot to mention context engineering techniques like compressing context history,
> remove old tool call history whenever necessary, add commands like /compact in agents,
> context summarization on all the agents . treat context as one of the budget as well. update
> requirement, tracker and readme md s accordingly once done thinking

---

## 1. Decisions log

| # | Decision | Why |
|---|---|---|
| D1 | GitHub repo `claude-multiagent`, **public** | User choice |
| D2 | LangSmith/OpenEval **off by default**, OpenTelemetry only for now | No API keys available yet; keeps everything local/free; can be enabled later via a settings flag without code changes |
| D3 | Planner + Coder agents run on `llama-server` (llama.cpp) hosting `DeepSeek-R1-Distill-Qwen-1.5B-UD-Q4_K_XL.gguf`, **fully GPU-offloaded**, flash attention on, quantized (q8_0) KV cache also on GPU, continuous batching with a small fixed slot count | Measured hardware: GTX 1650 Ti has only 4GB VRAM. The model's weights are ~1.1GB, so full GPU offload of *both* weights and KV cache fits comfortably with headroom — the CPU-KV-cache-offload trick the user suggested is for models whose weights nearly fill VRAM, which isn't the case here. Flash attention + quantized KV cache stretch that headroom further, allowing more context/parallel slots without more hardware. This is the most efficient option, not just the fastest one. |
| D4 | Tool agent runs `qwen2.5:7b-instruct` via Ollama, **CPU-only** (GPU disabled for this call) | Avoids VRAM contention with the always-resident llama.cpp server; tool-call formatting is latency-tolerant, so CPU is an acceptable trade for keeping total system load balanced and avoiding the 85%+ utilisation risk the user flagged |
| D5 | Orchestrator itself makes no LLM calls — pure LangGraph state machine / Python logic | Keeps hardware load minimal and the control flow deterministic and easy to reason about/test |
| D6 | Python 3.11 + `uv` for the whole project | Already installed and working on this machine; matches the pydantic/LangGraph/mem0/OpenTelemetry ecosystem |
| D7 | Inserted a new Phase 3 — **context engineering** — ahead of the Planning agent, renumbering old Phases 3–10 to 4–11 | User follow-up (§0.1): context compaction, tool-history eviction, per-agent summarization, and a `/compact`-equivalent needed to exist *before* any agent has a real conversation loop, not bolted on after. Also newly justified by a concrete hardware finding: `llama-server -np 2` makes this build's `--kv-unified` default to off, so the configured 8192-token context is actually split ~4096 tokens per Planner/Coder slot — a budget worth tracking explicitly. See REQUIREMENTS.md §6. |

## 2. Measured hardware (2026-09-26)

| Component | Spec |
|---|---|
| CPU | AMD Ryzen 7 4800H, 8 cores / 16 threads |
| RAM | ~16GB (15.4 GiB usable) |
| Discrete GPU | NVIDIA GeForce GTX 1650 Ti, **4096 MiB VRAM**, compute cap 7.5, driver 551.61, CUDA 12.4 |
| iGPU | AMD Radeon Graphics (display only — no CUDA/ROCm backend built into the local llama.cpp, so it isn't used for inference) |
| Local llama.cpp build | `E:\LLMCPP`, CUDA 12.4 x64 build (`ggml-cuda.dll` present), includes `llama-server.exe` |
| Local model | `DeepSeek-R1-Distill-Qwen-1.5B-UD-Q4_K_XL.gguf`, ~1.1GB on disk |
| Ollama models already pulled | `qwen2.5:14b-instruct`, `qwen2.5:7b-instruct`, `qwen2.5:7b`, `qwen3.5:latest`, `mistral:latest`, `nomic-embed-text:latest` |
| Tooling available | git 2.45.1, gh 2.95.0 (authenticated as `SumukhaK`, repo+workflow scopes), ollama 0.34.2, python 3.11.9, uv 0.11.1 |

## 3. Phase plan

Legend: ⬜ not started · 🔶 in progress · ✅ done · ⏸ deferred

| Phase | Scope | Status |
|---|---|---|
| 0 | Project scaffolding: CLAUDE.md, README/REQUIREMENTS/NON_TECHNICAL/TRACKER docs, `config/settings.py`, `.env.example`, `pyproject.toml`, first test, GitHub repo created & pushed | ✅ |
| 1 | Local model serving: tuned `llama-server` launch config (GPU offload, flash-attn, quantized KV cache, continuous batching), Ollama CPU-only helper for the tool model, a thin LLM client wrapper, smoke-test + micro-benchmark (tok/s, latency, VRAM) | ✅ |
| 2 | Shared infra: pydantic JSON schemas for inter-agent messages, OpenTelemetry logging/tracing wrapper, guardrail input filter, config loader — all unit-tested with a stubbed LLM client | ✅ |
| 3 | Context engineering: per-agent `ContextManager` (token budget, tool-history eviction, summarization compaction), hardware-derived budget helpers for the llama-server and Ollama backends, Ollama client now sets `num_ctx` explicitly | ✅ |
| 4 | Planning agent: read-only filesystem tools, clarification-question flow, plan schema + validator, prompt template | ✅ |
| 5 | Coding agent: TDD-enforcing workflow, sandboxed file write/edit tool, sandboxed pytest execution tool, mandatory step-review gate | ✅ |
| 6 | Tool agent: git/gh wrapper tools (branch/commit/push/PR), allowlisted commands only, hardware/emulator test runner (best-effort/stretch), retry + timeout + circuit-breaker logic | ✅ |
| 7 | Orchestrator: LangGraph state machine wiring all three agents, human-in-the-loop clarification interrupt, retry/escalation policy, hard step-budget circuit breaker, end-to-end test | ✅ |
| 8 | Memory layer: local mem0 (local embeddings via `nomic-embed-text`, local vector store), wired into Planner + Coder | ✅ |
| 9 | Guardrails & security hardening pass: expand injection/secret-exfiltration filters, sandbox/tool-allowlist audit | ✅ |
| 10 | Evaluation harness: golden task set, metrics (latency, token usage, tool success rate, hallucination rate + recovery, cost proxy), results appended to `README.md` | 🔶 |
| 11 | Polish: finalize architecture diagram, changelog, demo | ⬜ |

## 4. Phase log

- 2026-09-26 — Phase 0 started: hardware scanned, tooling verified, docs drafted, decisions D1–D6 recorded.
- 2026-09-26 — Phase 0 done: `config/settings.py` + tests pass (`uv run pytest`), lint clean
  (`uv run ruff check .`), committed directly to `main` as a repo-bootstrap commit (there was no
  base branch to PR against yet — see note below), public repo created and pushed:
  https://github.com/SumukhaK/claude-multiagent. PR-per-feature workflow starts at Phase 1.

**Note on Phase 0's commit:** it landed directly on `main` rather than via a branch+PR, because a
PR needs an existing base branch to merge into, and this commit *is* what created that base
branch. Every phase from here on gets its own branch, PR, self-review, and merge.

- 2026-09-26 — Phase 1 done on branch `feat/phase-1-local-model-serving`: `llama_server.py`
  (launch command + subprocess lifecycle + health check), `llama_client.py` and `ollama_client.py`
  (HTTP clients behind a shared `LLMResponse`/`LLMClient` shape), 20 new unit tests (all mocked —
  no GPU/binary needed to run the suite), plus `scripts/benchmark_llm.py` for manual hardware
  verification. Ran the benchmark for real on this laptop — results and the CPU-tool-agent
  latency trade-off are recorded in
  [REQUIREMENTS.md §3](REQUIREMENTS.md#3-hardware--local-inference-design). New dependency:
  `httpx` (lightweight, easy to mock in tests, needed for both HTTP clients).
- 2026-09-26 — Phase 2 started, split into individual branches/PRs per component (policy update:
  see CLAUDE.md §7). First component landed on `feat/agent-message-schemas`: `AgentMessage`
  envelope + `Plan`/`CodeChangeReport`/`ToolExecutionReport` discriminated-union payloads, with a
  validator enforcing the `error` field is set if-and-only-if `status == "error"`. 11 new tests,
  all passing.
- 2026-09-26 — Second Phase 2 component landed on `feat/observability-tracing`:
  `traced_call`/`FailureLog`/`configure_tracing` in `multiagent/observability/tracing.py`
  (OpenTelemetry spans + a structured JSON failure log for every agent/tool call). Console
  exporter only for now — no cloud account needed. 6 new tests using `InMemorySpanExporter`, all
  passing. New dependencies: `opentelemetry-api`, `opentelemetry-sdk`.
- 2026-09-26 — Third and final Phase 2 component landed on `feat/guardrails-input-filter`:
  `check_user_input` (blocks secret/credential-fishing requests), `sanitize_tool_output` (always
  wraps tool output as inert data), and `scan_tool_output_for_injection_markers` (flags
  instruction-like phrasing in tool output for logging, without blocking legitimate output) in
  `multiagent/guardrails/input_filter.py`. 9 new tests, all passing. **Phase 2 complete** — 49
  tests passing overall.
- 2026-09-26 — Phase 3 (context engineering, newly inserted per D7) landed on
  `feat/context-engineering`: `ContextManager` in `multiagent/context/manager.py` — token-budget
  tracking (`should_warn`/`needs_compaction`), tool-output eviction, summary compaction via an
  injected summarizer, and `maybe_compact()` as this system's non-interactive `/compact`.
  `llama_agent_token_budget()`/`ollama_agent_token_budget()` derive each agent's real usable
  context from measured hardware behavior (see REQUIREMENTS.md §6). Also updated
  `OllamaClient` (Phase 1) to set `num_ctx` explicitly from the new `ollama_tool_context_size`
  setting, so the tracked budget matches the model's actual runtime context window instead of
  drifting from it. 14 new context tests + 2 new Ollama client tests, 65 tests passing overall.
  **Phase 3 complete.**
- 2026-09-26 — Phase 4 started, first component landed on `feat/readonly-filesystem-tool`:
  `ReadOnlyFilesystem` in `multiagent/tools/filesystem.py` (`read_file`/`list_files`/`search_text`,
  sandboxed to a root directory — no write/delete methods exist at all, not just unused).
  Verified it blocks both `../` traversal and an absolute path outside the sandbox (a real
  pathlib gotcha: joining an absolute path onto a base path silently discards the base — the
  check runs on the final *resolved* path, so it still catches this). 10 new tests, 75 passing
  overall.
- 2026-09-26 — Second and final Phase 4 component landed on `feat/planning-agent-core`:
  prompt template (`multiagent/agents/planner/prompts.py`), response parser
  (`response_parser.py`), and `PlannerAgent.create_plan()` composing them with an injected
  `LLMClient`. Live-verified against the real llama-server + model on this machine (not just
  mocked tests) and found two real parser bugs this way — a naive greedy brace-match matching an
  unrelated `{"status": "ok"}` fragment in the model's own prose, and `<think>` stripping
  assuming a matched opening tag that this model's raw-completion output doesn't actually emit.
  Both fixed with a proper balanced-brace scanner and a fallback for a bare `</think>`. Also
  surfaced a real, honest limitation — this 1.5B model's reasoning is verbose and sometimes never
  reaches a valid answer even at 1200 `max_tokens` — recorded in REQUIREMENTS.md §8 rather than
  hidden, with the parser now failing loudly and correctly on that rather than silently
  mis-parsing. Also fixed a real design gap caught in self-review: an empty plan with no steps
  and no clarifying questions was reported as "ok" — a degenerate response the orchestrator
  would have silently treated as a completed empty plan — now reported as an error instead.
  27 new tests, 102 tests passing overall. **Phase 4 complete.**
- 2026-09-26 — Phase 5 started, first component landed on `feat/writable-filesystem-tool`:
  `WritableFilesystem` (`multiagent/tools/writable_filesystem.py`) extends `ReadOnlyFilesystem`
  rather than re-implementing sandbox-escape protection, adding `write_file`/`delete_file`, plus
  a new public `resolve_within_sandbox()` on the base class so a caller can validate a whole
  batch of proposed paths before writing any of them. TDD caught a real cross-platform bug:
  `Path.write_text()`'s default newline translation silently turned every `\n` into `\r\n` on
  Windows, while `read_file()` reads raw bytes with no translation — fixed with `newline=""`.
  10 new tests, 112 passing overall.
- 2026-09-26 — Second Phase 5 component landed on `feat/sandboxed-pytest-runner`:
  `SandboxedPytestRunner` (`multiagent/tools/pytest_runner.py`) — always
  `sys.executable -m pytest` as an argv list (never a shell string), every target validated
  against the sandbox *before* any subprocess launches, and a hard timeout that returns a
  structured `TestRunResult(timed_out=True)` instead of raising or hanging. 6 new tests
  (two run pytest as a real subprocess against a tmp project; the rest mock `subprocess.run`
  for the timeout/validation/argv-shape cases). 118 passing overall.
- 2026-09-26 — Third and final Phase 5 component landed on `feat/coder-agent-core`: extracted the
  shared reasoning-stripping/JSON-extraction primitives out of the Planner's parser (Phase 4)
  into `multiagent/agents/response_parsing.py`, so the Coder doesn't duplicate that
  security/correctness-sensitive logic — refactored with zero regressions (all of Phase 4's
  behavioral tests still pass unchanged). Added `CodeChangeProposal`/`ProposedFile`
  (deliberately *not* part of the inter-agent contract — see REQUIREMENTS.md §8's sibling note
  in the code — it never leaves the Coding agent), a matching response parser with TDD enforced
  at the schema level (a proposal with no test files fails validation), a coder prompt template,
  and `CoderAgent.implement_step()` composing an LLM, `WritableFilesystem`, and
  `SandboxedPytestRunner` into one call. A failing test run reports status "ok" with
  `tests_passed=False` (useful data for a retry policy, not a system error) and files are never
  rolled back on failure, matching how a human iterates; status "error" is reserved for actual
  execution failures, with every proposed path validated *before* any file is written
  (all-or-nothing). Live-verified twice against the real model, which surfaced two honest
  findings recorded in REQUIREMENTS.md §8: schema-valid JSON doesn't guarantee correct test
  content, and — reassuringly — the sandbox validation correctly caught and blocked a real,
  unpredictable (accidental, not malicious) absolute-path proposal from the model itself before
  writing anything. 27 net new tests, 145 tests passing overall. **Phase 5 complete.**
- 2026-09-26 — Phase 6 started, first component landed on `feat/git-tools`: `GitTools`
  (`multiagent/tools/git_tools.py`) — a fixed set of purpose-built operations
  (`create_branch`/`checkout`/`commit`/`push`/`create_pull_request`), no generic
  "run this git command" passthrough, so least privilege is structural here too. Every command
  is an argv list (never a shell string), and branch names are rejected outright if they start
  with `-` (a real, known git argument-injection class, not a hypothetical). Tests run
  `create_branch`/`commit` for real against a throwaway local repo; `push`/`create_pull_request`
  are always mocked, since they'd otherwise touch a real network/remote and the user's own
  authenticated `gh` account. 11 new tests, 156 passing overall.
- 2026-09-26 — Second Phase 6 component landed on `feat/resilience-retry-circuit-breaker`:
  `retry_with_fallback` and `CircuitBreaker` (`multiagent/resilience.py`) — generic, agent-agnostic
  bounded retry (an exception counts as a retry-worthy attempt, not a crash) and a hard backstop
  that opens after repeated consecutive failures across *separate* calls, on top of each call's
  own retry budget. No dependency on git/LLM/any specific agent, so Phase 7's orchestrator and
  the Tool agent (next) both reuse this instead of hand-rolling retry logic per call site.
  10 new tests, 166 passing overall.
- 2026-09-26 — Third and final Phase 6 component landed on `feat/tool-agent-core`:
  `HardwareTestRunner` (best-effort — detects `adb` availability honestly, no subprocess launched
  when it's missing) and `ToolAgent`, composing `GitTools` + the Ollama-backed
  `generate_commit_message` (retried, falls back to the raw summary text on failure) +
  `HardwareTestRunner`, with a shared circuit breaker across push/PR-create only (the
  network-dependent, correlated-failure-prone operations — not the local, deterministic
  create_branch/commit). `max_retries` means total attempts everywhere in this class, consistently.
  Live-verified against the real CPU-only Ollama model: commit-message generation — a short
  natural-language string, not nested JSON — came back clean on the first try, a useful
  counterpoint to Phase 4/5's findings recorded in REQUIREMENTS.md §8 — matching the LLM's job to
  what a small model can actually do reliably is itself a design decision. 20 new tests
  (13 ToolAgent + 7 HardwareTestRunner), 186 tests passing overall. **Phase 6 complete.**
- 2026-09-26 — Phase 7 started. First component landed on `feat/planner-review-step`: a new
  `StepReview` contract payload and `PlannerAgent.review_step()` — the mandatory review gate
  (CLAUDE.md §4) that didn't exist yet; Phases 4-6 only built the create-plan and
  implement-step/tool-action building blocks. Live-verified against the real model and found a
  real limitation, not assumed: given a step asking for `add(a, b)` and a report whose own
  summary said the test asserts `calculate(2, 3) == 5` — a mismatch spelled out in plain text —
  the review still came back `approved: true`. Recorded in REQUIREMENTS.md §8; the orchestrator
  (next component) therefore treats `tests_passed` as the primary gate and the review as an
  additional signal, not the deciding vote. 16 new tests, 202 passing overall.
- 2026-09-26 — Second and final Phase 7 component landed on `feat/orchestrator-graph`: the
  LangGraph state machine (`multiagent/orchestrator/`) wiring Planner → Coder → Planner-review →
  Tool into one loop, behind a plain `Orchestrator.run()`/`.resume()` API. Verified LangGraph's
  actual interrupt semantics with a standalone script before designing around them: a node
  resumes by *re-executing from its start*, so `clarification_node` contains nothing but the
  `interrupt()` call itself — all the real planning work stays in `plan_node`, which the graph
  loops back to, so resuming never re-runs an LLM call by accident. Every failure path (planner,
  coder, tests-failed-or-review-rejected, tool) gets the same bounded-retry-then-escalate
  treatment, and a `step_count` vs `max_orchestrator_steps` check in every router is the hard
  step-budget circuit breaker, checked before anything else. 11 tests passed on the first
  implementation attempt after tracing every scenario by hand before writing code — but the real
  end-to-end live run (real Planner+Coder, fake Tool agent) caught a genuine design gap missed by
  those same hand-traced tests: planning failures had *zero* retries while every other failure
  path had bounded ones, inconsistent with this project's own principle. Fixed
  (`plan_retry_count`, mirroring the Coder's pattern) and re-verified live — recorded in full,
  including a second live finding (the Coder mislabeling an implementation-only file as a "test
  file," which the schema's TDD check can't catch since it only requires a test file to *exist*,
  not that its content is a real test) in REQUIREMENTS.md §8. 11 new tests, 213 tests passing
  overall. **Phase 7 complete — all three sub-agents are now wired into one working loop.**
- 2026-09-26 — Phase 8 started. First component landed on `feat/memory-store`: `MemoryStore`
  (`multiagent/memory/store.py`) — mem0 with Ollama `nomic-embed-text` embeddings and an on-disk
  qdrant store, no LLM configured (`infer=False`), telemetry disabled before mem0 is imported,
  recall capped and wrapped with the tool-output guardrail. Read mem0's real API first and
  verified against the real Ollama embedder (`scripts/verify_memory.py`): store ~0.4s/4 memories,
  recall ~0.02s, GPU +4 MiB. Live checking found what the fakes couldn't — local qdrant allows one
  client per folder per process, so per-project clients crashed; fixed with
  `MemoryStore.for_project()` (TDD: test first, then fix). Also tested and rejected the hypothesis
  that nomic task prefixes would improve ranking (6/6 without vs 5/6 with). New dependencies:
  `mem0ai` (pulls qdrant-client, openai, posthog) and `ollama` (mem0's Ollama embedder requires
  the official client). 14 new tests, 227 passing overall. Orchestrator wiring is the next
  component.
- 2026-09-26 — Second and final Phase 8 component landed on `feat/orchestrator-memory`: the
  orchestrator takes an optional memory and appends recalled context (size-capped, guardrail-wrapped)
  for the Planner, Coder and reviewer; it remembers only verified outcomes — approved steps,
  clarification answers, completed tasks — never plans or failed attempts. The remembering side
  effect in `clarification_node` sits *after* `interrupt()`, so it runs exactly once (LangGraph
  re-executes a node from its start on resume). Extracted the shared orchestrator test fakes into
  `tests/orchestrator/fakes.py` first (the test file was heading past the ~400-line guideline),
  re-verifying the 11 existing tests unchanged. Verified with a real `MemoryStore` across two
  consecutive tasks: task 2, worded differently, received task 1's step summary and completion
  record. 12 new tests, 239 passing overall. **Phase 8 complete.**
- 2026-09-26 — Phase 9 started with an audit of what is actually true (REQUIREMENTS.md §10).
  Headline findings: `check_user_input` (Phase 2) is called nowhere in the running system; the
  Planner could read the project's own `.env`; `git add` received unvalidated paths; writes had no
  size cap. First component landed on `feat/protected-paths`: one shared protected-path policy
  (`.env*`, `.git/`, keys, the memory store; `.git/` hooks and `.github/` workflows write-protected)
  applied to every filesystem tool, checked on the *resolved* path after probing which spellings
  actually bypass a naive check on this Windows machine (all of them did, incl. an NTFS stream and a
  symlink). The Coder now validates every proposed write under the write policy plus a size cap before
  writing any file. A failing test also caught that `resolve()` doesn't reject a NUL byte here. 69 new
  tests, 308 passing overall. Remaining Phase 9 work (after the next entry): wiring the
  input guardrail, subprocess hardening.
- 2026-09-26 — Second Phase 9 component landed on `feat/secret-scanning`: an outbound secret
  scanner (kinds only, never values; conservative about placeholders so model-written test fixtures
  don't block every commit), applied to files staged by `GitTools.commit`, commit messages, PR
  title/body and `MemoryStore.remember`. Also hardened `git add`: explicit existing files only, none
  protected, `--` before paths so `-A` can't be read as an option. Test fixtures assemble fake tokens
  at runtime so no token-shaped literal ever reaches this public repo (GitHub push protection).
  Scanned all 95 tracked files as a false-positive check: zero findings. 38 new tests, 346 passing.
  Remaining: wire the input guardrail into the orchestrator, subprocess hardening.
- 2026-09-26 — Third Phase 9 component landed on `feat/orchestrator-input-guardrails`: the input
  guardrail is finally wired in (the audit found it was called nowhere), applied to the goal and
  every clarification answer before any agent sees them, with secret-in-input refusal and
  category-only logging; caller code context is wrapped as data. Before wiring it in, measured the
  existing filter on a realistic corpus: it blocked 4 of 25 attacks and wrongly blocked 3 of 24
  benign requests. Rebuilt it (normalisation, feature-noun exemption, tighter verb-to-noun gap,
  secret-store/exfiltration/malware patterns): 25/25 and 24/24 — but that corpus was tuned against,
  so a second, not-blind set was run: 7/12 attacks blocked, 11/12 benign allowed; the 6 remaining
  failures are pinned as strict xfails so the limits are documented in code. Hit a nasty tooling
  hazard on the way: scripted patching silently turned regex `\b` into backspace characters
  (invisible, and lint-clean), caught only because the output showed the word boundaries missing —
  now checked for control characters. 75 new tests, 421 passing (+6 expected failures).
  Remaining: subprocess hardening and the written audit.
- 2026-09-26 — Fourth and final Phase 9 component landed on `feat/subprocess-hardening`. Proved
  the gap first: a model-written test could read every secret in the parent's environment (a demo
  API token and `GITHUB_TOKEN` both printed); the same probe now prints `None None`. The pytest and
  hardware runners get a scrubbed environment; pytest output is captured to a temp file and only the
  tail read back. The tool-allowlist audit found `HardwareTestRunner.run(command=...)` would run any
  argv once `adb` merely existed — now adb-only. The written audit (REQUIREMENTS.md §10.1) records
  what is mitigated and what is not, including that CLAUDE.md §4's "no agent gets write + git +
  network" is not true in practice for the Coder, whose pytest runs execute model-written code with
  the developer's full privileges. 26 new tests, 447 passing (+6 documented expected failures).
  **Phase 9 complete.**
- 2026-09-26 — Phase 10 started. First component landed on `feat/eval-metrics`: Wilson
  intervals and percentiles (`stats.py`) and the metering wrappers (`metering.py`) that observe LLM
  calls, agent outcomes and tool operations by wrapping the injected objects — no agent code
  changed, verified by running the real orchestrator unchanged through metered agents. Metric
  definitions were fixed in REQUIREMENTS.md §11 *before* any number existed, each derived from
  observable evidence (a hidden acceptance test), never from the model's own claims. 27 new tests,
  465 passing. Next: the golden task set, then the runner and the real run.
- 2026-09-26 — Second Phase 10 component landed on `feat/eval-golden-set`: eleven golden tasks
  (features, bug fixes, one underspecified task, two adversarial, one benign-but-scary-sounding),
  each with a hidden acceptance test. The set is itself tested with real pytest runs: every
  acceptance test passes on its reference solution and fails when nothing is done, is invisible to
  the agents, and is consistent with the input guardrail. 38 new tests, all passing first time;
  503 total. Next: the runner, the real run, and publishing results.
