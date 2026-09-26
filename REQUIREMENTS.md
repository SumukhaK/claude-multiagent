# Technical Requirements & Design

Audience: engineers. For phase status see [TRACKER.md](TRACKER.md); for governance/process rules
see [CLAUDE.md](CLAUDE.md); for a plain-English overview see [NON_TECHNICAL.md](NON_TECHNICAL.md).

## 1. Functional requirements

1. Accept a coding/debugging task from the user in natural language.
2. A **Planning agent** must, before producing a plan:
   - read the existing relevant code (never assume the codebase's current state),
   - ask the user clarifying questions when the request is ambiguous or underspecified,
   - enumerate edge cases,
   - produce a strict, versioned, step-by-step JSON plan for the Coding agent.
3. A **Coding agent** must, per plan step:
   - read any existing/overlapping code before writing or modifying anything,
   - write a failing test first, then the implementation (TDD),
   - run the tests (via the sandboxed execution tool) and report pass/fail back,
   - never proceed to the next step until the Planning agent has reviewed the current one.
4. A **Tool agent** must:
   - own all git/GitHub operations: branch creation, commits, pushes, PR creation,
   - own any hardware-dependent test execution (physical device / emulator), best-effort,
   - report results/failures back to the orchestrator in the shared JSON schema, never edit code.
5. An **Orchestrator** must:
   - drive the plan → execute-step → review-step loop and enforce it strictly,
   - be the only component that surfaces clarification questions to the user,
   - enforce a hard retry cap per failure and a hard step budget per run (no infinite loops),
   - escalate exhausted retries/step budgets to the user with a clear failure report instead of
     retrying silently or looping.
6. All inter-agent communication is a validated structured JSON message (pydantic model), never
   free text.
7. All agent/tool calls are logged, traced (OpenTelemetry spans), and failures are recorded to a
   dedicated failure log, for later evaluation.
8. A memory layer (mem0, local backend) persists cross-step context (past decisions, file
   summaries) within a project/session scope.
9. Guardrails must detect and refuse attempts (from the user or from tool/sub-agent output) to
   exfiltrate secrets/credentials or to redirect any agent via injected instructions in tool
   output.
10. An evaluation harness must run a fixed "golden" task set and report: latency, token usage,
    tool success rate, hallucination rate and recovery rate, and a cost proxy (local inference
    is free, so token counts stand in for cost) — published at the bottom of `README.md`.

## 2. Non-functional requirements

- **Local-first, zero paid dependency.** The core loop must run with no internet access beyond
  optional GitHub operations and no paid API keys.
- **Hardware headroom.** Combined CPU/GPU utilisation must be designed to avoid sustained 85%+
  usage on either resource (see §3) — this laptop is used for other things.
- **Least privilege.** No sub-agent has more tool access than its role strictly requires.
- **Determinism where it matters.** Retry counts, step budgets, and the plan→execute→review loop
  are deterministic Python control flow, not left to LLM judgement.
- **Testability.** Every component must be unit-testable with a stubbed LLM client, independent
  of whether `llama-server`/Ollama are actually running.
- **File size discipline.** No source file over ~400 lines.

## 3. Hardware & local inference design

Measured specs and the decisions derived from them are recorded in
[TRACKER.md §2–3](TRACKER.md#2-measured-hardware-2026-09-26) (decisions D3–D5). Summary of the
`llama-server` launch configuration for Phase 1:

| Setting | Value | Reason |
|---|---|---|
| GPU layers (`-ngl`) | all layers (999) | Model is ~1.1GB — fits GPU entirely, no partial-offload complexity needed |
| KV cache location | GPU (default, not `--no-kv-offload`) | 4GB VRAM − ~1.1GB weights leaves ~2.9GB; more than enough for the KV cache at the context sizes this project needs, so there is no reason to pay the latency cost of spilling KV cache to CPU |
| Flash attention | on (`--flash-attn`) | Reduces KV cache memory and improves throughput; supported on Turing (compute cap 7.5) |
| KV cache quantization | `q8_0` for K and V | Further shrinks KV cache memory, allowing more context/parallel slots inside 4GB without a meaningful quality hit |
| Continuous batching | on (`llama-server` default) | Lets Planner/Coder requests share the server efficiently without blocking |
| Parallel slots | small fixed number (2) | One slot each for Planner and Coder is enough for this project's sequential-with-occasional-overlap usage pattern; more slots would burn VRAM/context for no real benefit here |
| CPU threads for the server | capped, not "all 16" | Leaves CPU headroom for the Tool agent's Ollama (CPU-only) call and the Python orchestrator process |

Tool agent model: Ollama `qwen2.5:7b-instruct`, invoked with GPU disabled for that call
(`num_gpu: 0` in the Ollama request options) so it never competes with `llama-server` for the
4GB of VRAM.

All of the above are config values in `config/settings.py`, not hardcoded in agent code — they
can be re-tuned (or the model swapped) without touching orchestration logic.

**Measured on this hardware (`scripts/benchmark_llm.py`, 2026-09-26):**

| Metric | Result |
|---|---|
| llama-server cold start → healthy | ~21s |
| GPU memory with model loaded | ~1.2GB of 4GB VRAM |
| GPU memory after server stop | back to 0 MiB (clean release) |
| Generation throughput (GPU) | ~48–88 tok/s |
| Ollama tool-agent call, CPU-only | ~1.4 tok/s, GPU stayed at 0 MiB throughout |

The GPU-offload design is confirmed: weights + KV cache both fit with ~2.8GB of VRAM to spare,
and the CPU-only Ollama call never touched the GPU, so the two never contend for VRAM. The
CPU-only tool-agent path is honestly slow (~20s+ for a short structured response) — acceptable
for infrequent git/PR calls, but flagged here as a real trade-off to revisit in a later phase
(e.g. a smaller/faster tool-calling model, or letting the tool agent use a few GPU layers when
llama-server is idle) rather than glossed over.

## 4. Inter-agent JSON contract (sketch — finalised in Phase 2)

Every message between the orchestrator and a sub-agent is a pydantic model with at least:

```
agent: Literal["planner", "coder", "tool"]
task_id: str
status: Literal["ok", "needs_clarification", "blocked", "error"]
payload: dict           # shape depends on agent + status
retry_count: int
error: str | None
```

Plan steps, code-change reports, and tool-execution reports are typed payload sub-models,
not free-form dicts, so a malformed response fails validation loudly instead of silently.

## 5. Tools & libraries (planned)

| Purpose | Choice | Notes |
|---|---|---|
| Agent orchestration | LangGraph | State machine for the plan/execute/review loop |
| Local LLM serving (Planner/Coder) | llama.cpp `llama-server` (`E:\LLMCPP`) | CUDA build already present |
| Local LLM serving (Tool agent) | Ollama, `qwen2.5:7b-instruct`, CPU-only | Already pulled |
| Observability | OpenTelemetry | Spans + structured logs; console/local exporter, no cloud account needed |
| Evaluation (optional, later) | LangSmith / OpenEval | Off by default, free tier only, gated behind a settings flag — needs the user's API keys first |
| Memory | mem0 (local vector store) | No cloud dependency |
| Config | pydantic-settings | Single `config/settings.py`, sourced from `.env` |
| Data validation / contracts | pydantic | JSON schemas for all inter-agent messages |
| Testing | pytest | TDD for every feature |
| Packaging | uv | Already installed |
| Git/GitHub | git, `gh` CLI | Already authenticated |

## 6. Context engineering (treat context as a budget)

Added after Phase 2, before building the Planning agent — context needs to be managed *before*
any agent has a real conversation loop, not retrofitted after. See TRACKER.md decision D7 for
why this became its own phase rather than a Phase 3/4 footnote.

**Why this is a hard requirement here, not a nice-to-have:** llama-server runs with an explicit
`-np 2` (parallel slots). Because the slot count is explicit rather than `auto`, this build's
`--kv-unified` defaults to *off* (confirmed via `llama-server --help`), so the configured
`-c 8192` context is split evenly across the 2 slots — each of the Planner and Coder effectively
gets **~4096 tokens**, not 8192. That's a small budget for a multi-step plan-execute-review loop
with tool output in it, so compaction is load-bearing, not optional headroom.

- **Every agent's conversation history is a `ContextManager`** (`multiagent/context/manager.py`),
  tracked against a token budget derived from the real, measured hardware split:
  `llama_agent_token_budget()` for Planner/Coder (ctx_size ÷ parallel slots, minus a response
  reserve), `ollama_agent_token_budget()` for the Tool agent (its own configured
  `ollama_tool_context_size`, minus a reserve). The Ollama client now sets `num_ctx` explicitly
  from that same setting, so the tracked budget matches the model's *actual* runtime context
  window instead of silently drifting from it.
- **Tool-call history is pruned before anything else.** `evict_old_tool_output()` keeps only the
  most recent N tool results verbatim and replaces older ones with a short placeholder — tool
  output (file contents, test logs) is usually the largest and least reusable part of a
  transcript, so it's the first thing dropped.
- **Compaction/summarization is the fallback**, not the first move. `compact()` collapses
  everything except the most recent turns into a single summary turn, produced by an injected
  summarizer function — decoupled from any specific LLM backend, so the same `ContextManager` is
  reusable across the llama.cpp-backed and Ollama-backed agents.
- **`maybe_compact()` is this system's `/compact`.** There's no interactive REPL here to type a
  slash command into, so the equivalent is procedural: the orchestrator calls `maybe_compact()`
  after every agent turn, which evicts stale tool output first and only pays for a summarization
  pass if eviction alone didn't bring the transcript back under budget.
- **Two thresholds, not one:** `warning_ratio` (default 0.75) is a soft signal an agent/orchestrator
  can log or react to proactively; `hard_ratio` (default 0.9) is where compaction actually
  triggers — leaving headroom before the model's real context limit, not right up against it.
- **Token counts are an approximation** (`estimate_tokens`, ~4 characters per token), not an exact
  count from the model's own tokenizer. An exact count would mean a round trip to llama-server's
  `/tokenize` endpoint on every turn just for budget bookkeeping, which isn't worth the extra
  hardware/latency cost — `token_counter` is an injectable dependency, so a more precise counter
  can be swapped in later without changing `ContextManager` itself.

## 7. Explicit non-goals (for now)

- Fine-tuning or training any model.
- Running more than one heavy local model on the GPU simultaneously.
- Guaranteeing hardware/emulator test execution — best-effort only, given the hardware ceiling.
- Multi-user support, auth, or hosting this as a service.

## 8. Known limitations (measured, not assumed)

- **The Planner's response parser is robust; the local model's reliability on this task is not
  yet good, and that's measured rather than guessed.** Live-verified against the real
  `DeepSeek-R1-Distill-Qwen-1.5B` server (Phase 4): its reasoning prefix regularly runs past
  1000 tokens before reaching an answer, and even at 1200 `max_tokens` its reasoning was
  sometimes too unfocused to reach a complete, schema-valid JSON plan at all. `parse_plan_response`
  correctly raises `PlanParsingError` in that case — the fix in Phase 4 was making the parser fail
  loudly and correctly on messy/truncated output (a naive greedy brace-match was matching an
  unrelated fragment in the model's prose), not making the small model itself more reliable.
- **Likely contributing factor, not yet tried:** the Planner currently talks to llama-server's raw
  `/completion` endpoint with a plain-text prompt — no chat template is applied, even though
  DeepSeek-R1-Distill models are tuned for chat-formatted turns. Trying the OpenAI-compatible
  `/v1/chat/completions` endpoint with proper system/user roles is a reasonable next experiment,
  but is deliberately left as a follow-up rather than iterated on ad hoc here.
- **This is exactly what Phase 10's evaluation harness exists to measure systematically** (plan
  success rate, hallucination rate) instead of relying on a handful of manual runs like this one.
- **The Coder shows the same pattern, one level deeper: schema-valid JSON doesn't mean correct
  content.** Live-verified (Phase 5): the model did produce a parseable `CodeChangeProposal` for
  a simple "add a function" step, but the proposed test asserted against an unrelated
  pre-existing function instead of the one it was asked to implement — a test that wouldn't
  actually verify the requested change even though it's well-formed JSON. The implementation
  file it proposed alongside it, by contrast, was correct. `parse_code_change_response` did its
  job (the JSON was genuinely valid), but correctness of the *content* is a separate, harder
  problem this parser was never meant to solve, and Phase 10 is where it gets measured rather
  than assumed.
- **The sandbox validation was verified against real, unpredictable model output, not just
  contrived test cases — and it worked.** In a separate live run, the model proposed a path like
  `/python/calc.py` (an accidental absolute-looking path, not malicious). `CoderAgent` rejected
  it before writing anything and reported a clear error, exactly as the all-or-nothing
  pre-validation in Phase 5 was designed to do. This is the kind of thing worth confirming
  against the real, messy model rather than trusting the synthetic escape attempts in unit tests
  alone.
- **A counterpoint, not just more of the same problem: scoping the LLM's job down to short
  natural-language generation makes it reliable, even on the weaker CPU-only model.** Live-verified
  (Phase 6): the Tool agent's commit-message generation — a single short natural-language string,
  not nested structured JSON — asked the CPU-only `qwen2.5:7b-instruct` (Ollama) to summarize "added
  a /health endpoint... returning {'status': 'ok'}" and got back `"Added /health endpoint to
  FastAPI app returning {"status": "ok"}"` in ~14.4s for 16 tokens (consistent with the ~1.4 tok/s
  measured in Phase 1) — clean, correct, no parsing needed at all. The lesson isn't "this model
  is good" or "that model is bad" — it's that matching the task's shape to what a small model can
  actually do reliably (short generation vs. nested schema-constrained JSON with real code
  content) is itself a design decision, and this project deliberately narrowed the Tool agent's
  LLM usage to exactly the part that's reliable, keeping every git/gh action itself deterministic.
