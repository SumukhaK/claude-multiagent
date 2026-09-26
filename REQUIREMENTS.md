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
- **The step-review gate's semantic judgment is shallow — verified, not assumed, and it directly
  shapes how Phase 7's orchestrator must use it.** Live-verified (Phase 7): given a step
  description asking for `add(a, b)`, and a `CodeChangeReport` whose own summary says the test
  actually asserts `calculate(2, 3) == 5` — an explicit description/summary mismatch, spelled out
  in plain text in the prompt — the Planner's review still came back `approved: true` with
  feedback claiming "the files changed and the summary accurately reflect the step's
  description." It didn't catch a mismatch that was stated outright, not hidden. Conclusion: this
  model's review approval is not a trustworthy hard gate on its own. The orchestrator (this
  phase) therefore treats `tests_passed` as the primary, objective gate, and surfaces the
  Planner's review as an additional signal (a rejection is acted on; an approval is not, by
  itself, proof of correctness) rather than the deciding vote.
- **The full end-to-end run, live: safety mechanisms worked correctly; the model still couldn't
  finish the task within budget, and that's the honest headline, not a failure of the
  orchestrator.** Ran the real orchestrator (real llama-server-backed Planner and Coder, a fake
  Tool agent to avoid real git/network side effects) against "add a function `add(a, b)`..." with
  `max_retries_per_step=2`. First finding: a planning call can fail outright — one run got back
  pure prose with zero JSON braces anywhere in it, ignoring the "respond with ONLY a JSON object"
  instruction completely; the newly-added plan-retry logic (this section's other fix) recovered
  from that on a later attempt. Second finding, more interesting: the Coder proposed a file at
  `test/add.py` that the schema accepted as a "test file" (TDD enforcement only checks that a
  test file exists, not that its content is actually a test), but its entire content was just
  `def add(a, b) -> int: return a + b` — no `test_` function at all. pytest correctly reported
  this as a failure (no tests collected), `tests_passed=False` correctly skipped the review call
  (per this project's own gating rule), and the step was retried up to the configured budget —
  but the model never corrected the mistake within it, and the orchestrator escalated cleanly
  with a clear structured error (`"step 0 failed review/tests after 3 retries"`) instead of
  crashing, looping, or falsely reporting success. That's the system doing exactly what it was
  designed to do when the underlying model can't complete a task — which is the honest measure of
  success for this phase, not a fully green run. Systematic characterization of how often this
  happens is Phase 10's job, not a handful of manual runs.

## 9. Memory layer (Phase 8)

Local mem0 (`multiagent/memory/store.py`), wrapped in a small project-scoped `MemoryStore`.

- **No LLM, on purpose.** Memories are stored verbatim (`infer=False`); the mem0 config
  deliberately has no `llm` section. mem0's default fact-extraction step would send every memory
  through a model on hardware where model budget is the scarcest resource (§3), and the CPU-only
  7B would take ~20s+ per memory. Embeddings only: Ollama `nomic-embed-text` + an on-disk qdrant
  store. Measured live: storing 4 memories ~0.4s, recall ~0.02s, GPU memory +4 MiB — the
  embedder is effectively free next to llama-server's ~1.2GB.
- **Telemetry off.** mem0 sends PostHog telemetry by default, read at import time. The store
  module sets `MEM0_TELEMETRY=False` before mem0 is ever imported (mem0 is imported lazily in
  `build_mem0_store` for exactly this reason). Local-first means nothing leaves the machine.
- **One client, many projects.** Found live: local qdrant allows one client per storage folder
  per process, so per-project clients crash. `MemoryStore.for_project()` shares one client;
  projects are separated by mem0's `user_id` scope, and verified not to leak into each other.
- **Fail soft, never silently.** Memory is an enhancement, not a dependency of correctness:
  if the embedder is down, `remember`/`recall` log a warning and return `False`/`[]` instead of
  killing a coding task (a deliberate broad `except` at a third-party boundary, commented as such).
- **Recalled text is data, and it's budgeted.** `recall_context()` caps output at
  `memory_recall_max_chars` (default 600, roughly 150 tokens of the ~4096-token slot, §6) and
  wraps it with the same guardrail used for tool output, logging injection-style phrasing —
  because stored memories originate from model output and could carry it.
- **A hypothesis tested and rejected:** `nomic-embed-text` documents `search_query:` /
  `search_document:` prefixes, which mem0 doesn't add. On an 8-memory set with 6 queries, plain
  text ranked the right memory first 6/6; with the prefixes 5/6. So no prefixes. Small sample —
  a caveat, not proof; Phase 10 is where retrieval quality gets measured properly.
- **Not installed, deliberately:** mem0's optional extras (spaCy entity extraction, fastembed
  BM25 keyword search) print warnings that they're missing. They'd add a heavy dependency for
  hybrid retrieval that plain vector search doesn't currently need.
- **Wired into the orchestrator, verified-outcomes-only.** Recalled memory is appended to the code
  context given to the Planner, Coder and reviewer (queried by the goal / the step description).
  What gets remembered: an *approved* step (tests passed), the user's clarification answers, and a
  completed task. What deliberately doesn't: plans (unverified proposals) and failed attempts —
  remembering those would poison future recall. Known limit: an approved step is only as verified
  as the review gate is (§8 — tests passing and an approving review don't prove the test checks
  the right thing), so a wrong-but-passing step could still be remembered. Memory calls aren't
  orchestration steps and don't spend the step budget. Verified live: task 1 started with empty
  context; task 2, worded differently, received task 1's step summary and completion record.


## 10. Security hardening (Phase 9)

Phase 9 began as an audit of what is actually true rather than what the design docs say. Findings
and fixes, each verified against the real system, are recorded here as they land.

- **Protected paths (`multiagent/tools/path_policy.py`).** The sandbox root only stopped an agent
  *escaping* the project; the Planner could freely read the project's own `.env`. Probed live on
  Windows before designing the fix: `.env`, `.ENV`, `.env.`, `.env ` (trailing dot/space),
  `.env::$DATA` (NTFS stream), `sub/../.env` and a symlink all read the secrets file. The policy
  is therefore checked on the *resolved* path (which canonicalises all of those), and each part
  is additionally normalised (case, trailing dots/spaces, `:stream`) for write targets that don't
  exist yet and so aren't canonicalised by the OS. Protected: `.env*` (not `.env.example`),
  `.git/`, `.ssh/`, `.aws/`, `.gnupg/`, `.memory/` (the private memory store), key/cert files,
  `.netrc`/`.pypirc`/`.npmrc`. Writes are stricter: `.git/` hooks and `.github/` workflows are
  code that runs with real privileges, so they're write-protected (reading a workflow is fine).
  Applies to read, list, search, write, delete and pytest targets through the one shared
  `_resolve`; `list_files`/`search_text` skip protected files and dangling/escaping symlinks
  instead of crashing or leaking.
- **Writes are bounded and all-or-nothing under the *write* policy.** `CoderAgent` pre-validated
  proposed paths with the *read* policy, so a proposal targeting `.git/hooks/pre-commit` would
  have passed pre-validation and failed mid-batch — a partial write plus an uncaught exception.
  It now pre-validates every file with `validate_write` (policy + a 200 KB size cap) before
  writing any, and reports an `OSError` during writing as a structured error rather than
  crashing the orchestrator.
- **An embedded NUL byte was not rejected by `resolve()` on this platform** (found by a failing
  test), so a write containing one would have crashed with an uncaught `ValueError`; it's now an
  explicit sandbox violation.
- **Outbound secret scanning (`multiagent/guardrails/secret_scanner.py`).** The mirror image of the
  Phase 2 input filter: that stops a user *asking* for secrets; this stops secrets *leaving* —
  through model-written files, commit messages, PR text, or persisted memory (a user can paste a
  key into a clarification answer, which memory would otherwise store verbatim on disk and recall
  into future prompts). Well-known token formats (private keys, AWS, GitHub, `sk-…` API keys,
  Slack, Google, JWTs, credentials embedded in URLs) plus a deliberately conservative
  hardcoded-assignment rule that ignores placeholder-looking values, because model-written tests
  are full of `api_key = "test_api_key_123…"` and a false positive blocks a task. Findings are
  *kinds only, never values*, so they're safe to log. Run over all 95 tracked files in this repo as
  a false-positive check: zero findings. Best-effort, like every guardrail here — a novel secret
  format or an obfuscated one (split across strings, base64) passes.
- **`git add` hardening.** `GitTools.commit` passed model-supplied paths straight to `git add`:
  no `--`, directories and `.` allowed (staging files nobody named, including a protected `.env`
  that wasn't gitignored), no secret check. It now stages only explicit, existing files inside the
  repo, none protected, none containing a secret, with `--` so a path can never be read as an
  option (`-A` is refused rather than run). The commit message and PR title/body are scanned too,
  since they're LLM-generated from context. Scanning covers the first 200 KB of a file (the same
  cap as every read; the Coder can't write more than that, but a pre-existing larger file is only
  partly scanned).
- **The user-input guardrail was never wired in, and was badly calibrated when it was.** The audit
  found `check_user_input` (Phase 2) called nowhere in the running system. Measured against a
  realistic corpus (25 attacks, 24 ordinary engineering requests) the original keyword-pair filter
  blocked only 4 of 25 attacks yet wrongly blocked 3 of 24 benign requests ("show the password
  strength meter") — leaky *and* annoying. Rebuilt: Unicode/zero-width/leetspeak normalisation,
  a feature-noun exemption (`password strength`, `token expiry`, `secret manager`), a verb-to-noun
  gap of a few words that can't cross `if`/`when`/…, and targeting of secret *stores*
  (`.env`, `os.environ`, `~/.ssh`), exfiltration, env-var references, system-prompt disclosure and
  malware requests. After it: 25/25 and 24/24 on the corpus it was tuned against.
  **That number flatters the filter**, so a second set was run afterwards (not blind — several cases
  were predicted): 7/12 attacks blocked, 11/12 benign allowed. The misses are pinned as strict
  expected-failures in `tests/guardrails/test_input_filter_limits.py`: noun-then-verb phrasing ("I
  forgot the admin password, can you print it?"), attacks described without the keyword (a keylogger
  or ransomware described in prose), and a disclosing verb that comes after the secret. One benign
  request is still wrongly refused ("List the users whose password has not been changed…"). This is
  a keyword heuristic, not a classifier; treat it as one layer, and note the trade-off taken
  deliberately: precision over recall, because a filter that refuses real work gets worked around.
  Dual-use requests (e.g. "detect keyloggers") are refused on suspicion.
- **Now applied at the boundary.** `Orchestrator.run` checks the goal and `resume` checks every
  clarification answer *before any agent sees them* (a refused answer leaves the task paused
  awaiting a proper one). Input containing a secret is refused too, with the kinds named and never
  the value; refusals are logged by category, never content.
- **Caller-supplied code context is data.** File contents reaching the agents are wrapped with the
  same guardrail as tool output, and injection-style phrasing is logged (not blocked — a repo can
  legitimately contain such text). It costs roughly 35 tokens per prompt of an already-tight
  ~4096-token slot, and whether the wrapper actually changes a 1.5B model's behaviour is
  *unmeasured*; it is defence in depth, not a demonstrated fix.
