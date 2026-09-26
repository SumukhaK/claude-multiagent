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
- **Subprocess hardening.** Verified live first: a model-written test could read every secret in
  the parent's environment (`os.environ` showed both a demo API token and `GITHUB_TOKEN`). The
  pytest and hardware runners now pass a scrubbed environment (`subprocess_env.py`: variables whose
  names contain KEY/TOKEN/SECRET/PASSWORD/PASSWD/CREDENTIAL/AUTH/PRIVATE are dropped by name; a
  denylist rather than an allowlist because it is far less likely to break the interpreter); the
  same probe now prints `None None`. Pytest output goes to a temp file of which only the last 20 KB
  is read back, so a test printing gigabytes can't balloon this process's memory and pytest's
  summary (at the tail) survives. `GitTools` is deliberately *not* scrubbed — `git`/`gh` need
  their credentials.
- **Tool-allowlist audit result.** `HardwareTestRunner.run(command=...)` checked only that `adb`
  existed, then ran whatever argv it was given — an arbitrary-command primitive inside the Tool
  agent, contradicting the "fixed operations, no generic passthrough" principle the other tools
  follow. Nothing called it with model input, but the API allowed it; it now refuses anything
  whose first element isn't exactly `adb`.

### 10.1 Threat model: what is mitigated, and what is not

Verified by reading the code: the Planner has no tools of its own (the orchestrator supplies its
context); the Coder has `WritableFilesystem` and `SandboxedPytestRunner`; the Tool agent has
`GitTools` and `HardwareTestRunner`; the orchestrator has no tools and no LLM.

**Mitigated (each with a test):** path escape and access to protected files (`.env`, `.git/`,
keys, the memory store) through any filesystem tool; writes to git hooks and CI workflows;
oversized writes; partial writes from a mixed proposal; staging of directories, protected files or
files containing a secret; `git add` option injection; secrets in commit messages, PR text and
memory; secret-fishing and malware requests at the input boundary (to the measured extent below);
secrets in the environment reaching model-written tests; unbounded test output; arbitrary commands
through the hardware runner.

**Not mitigated — read this before trusting the system with anything that matters:**

1. **CLAUDE.md §4 says no agent gets write, git and network access at once. In practice the Coder
   effectively does:** it writes code and then *executes* it via pytest, and that code runs with
   the developer's full OS privileges — it can read any file on the machine (the path policy only
   restricts *our tools*, not code the tests run), open network connections, and spawn processes.
   The environment scrub and output cap reduce the blast radius; they are not isolation. Real
   isolation needs a container, VM or Windows Sandbox with no network — out of scope for a
   laptop-local portfolio project, but the honest answer to "is it safe to point at code you don't
   control?" is **no**.
2. On timeout Windows kills the pytest process but not grandchildren it spawned.
3. The temp file bounding test output is limited only by the timeout, not by disk size.
4. The input guardrail is a keyword heuristic: on a second, not-blind set it blocked 7/12 attacks
   and refused 1/12 ordinary requests (six pinned failures in `test_input_filter_limits.py`).
   The secret scanner is pattern-based: novel or obfuscated secrets pass.
5. Whether wrapping context "as data" changes a 1.5B model's behaviour is unmeasured.
6. Memory can retain a wrong-but-passing step (the review gate is weak, §8).
7. `gh` acts as the developer's authenticated GitHub account; a PR is a real public action.

## 11. Evaluation (Phase 10)

**Metric definitions, fixed before any number was produced** (so they can't be reshaped to flatter
the results). Each is computed from observable evidence, never from the model's own claims:

| Metric | Definition |
|---|---|
| Task success | The orchestrator reports `done` **and** a hidden acceptance test (never shown to any agent) passes on the produced code |
| Hallucinated success | The orchestrator reports `done` but the hidden acceptance test fails — the system claimed something it didn't deliver. Directly measures the weak review gate (§8) |
| Fake-test rate | A file the Coder proposed as a test contains no `test_` function (the failure mode found live in Phase 7) |
| Recovery rate | Of runs that hit at least one failed attempt (an agent error, or the Coder's tests failing), the share that still ended in task success |
| Tool success rate | Per operation, the share of real git calls (branch, commit, push) that succeeded, against a throwaway local repo with a local bare remote — never GitHub |
| Guardrail correctness | For adversarial tasks: the share correctly refused; for benign tasks: the share not wrongly refused |
| Latency | Per LLM call by role (p50/p95) and per task wall-clock |
| Cost | Total tokens (prompt + completion) and summed LLM seconds per task. Marginal dollars are $0 for local inference; no reference price is invented |

Runs are non-deterministic (the model samples), so each task is repeated and every rate is
reported with a **Wilson 95% interval** rather than a bare percentage — with this few runs the
intervals are wide, and the report says so instead of hiding it.

Metering wraps the injected LLM client, agents and tools (`multiagent/evaluation/metering.py`), so
the agents themselves are unchanged and the same wrappers work against fakes in tests.

### 11.1 The golden set (`multiagent/evaluation/golden_tasks.py`)

Ten tasks: five features (one of them, "password strength", is benign but security-flavoured, so
a naive keyword filter would wrongly refuse it), two bug fixes (the agents are shown the buggy
code), one *deliberately underspecified* task that should provoke a clarifying question, and two
adversarial tasks that the input guardrail should refuse. (An earlier revision of this document
and PR #23 said "eleven" — the password-strength task had been counted twice.) Each implementation task pairs a
plain-English goal naming its file and function with a **hidden acceptance test** that is written
into the sandbox only after the run.

Every metric rests on these, so the set itself is tested (`tests/evaluation/test_golden_set.py`,
real pytest subprocesses): each acceptance test **passes on its reference solution and fails when
nothing is done** (an agent that does nothing can't score), is invisible to the agents, and each
goal is consistent with the input guardrail. The tasks are simple on purpose — the evaluation
measures the *system's* loop and honesty, not how hard a problem the model can solve — but that
also means results say little about realistic software tasks.

### 11.2 The harness

`scripts/run_eval.py` starts llama-server (Planner/Coder) and uses Ollama (Tool agent), then runs
every golden task `--repeats` times (interleaved) through the **real** agent classes, sandboxed
filesystem and pytest runner, and **real git** against a throwaway repo with a *local bare remote*
— never GitHub. Results stream to `evals/results/<timestamp>.jsonl` as each run finishes, so an
interrupted run keeps what it has; the aggregate is rendered to `evals/results/<timestamp>.md`
and published into a marked section of the README, replaced (not duplicated) on re-runs.

Design choices worth knowing:
- **The runner is model-agnostic.** `run_task` takes a factory building the orchestrator for a
  sandbox and meter, so it is tested with fakes; the wiring of the real stack is smoke-tested with
  fake LLM clients, including a scripted model that drives the real Planner, Coder, reviewer and
  Tool agent (real files, real pytest, real commit and push to the local remote) to a genuine
  success — so a failure in a real run is the model's, not the harness's.
- **Pull-request creation is stubbed and labelled** (no GitHub remote to open one on), and
  excluded from tool success so a stub can't inflate the rate.
- **Memory is off** so tasks are independent of each other.
- **A crash in one run is recorded as `crashed`** and never aborts the suite.
- **Runs that do not succeed keep their evidence** under `evals/artifacts/<stamp>/<task>-<n>/`
  (gitignored, local debugging only): `summary.json` (outcome, error, the hidden test's output,
  per-step reports), `llm_responses.jsonl` (every raw model response; prompts are not kept) and a
  copy of the sandbox without `.git`. Successful and correctly refused runs leave nothing.
- **Orchestrator budget for evaluation is 12 steps** (not the default 25), to bound a run that is
  going nowhere; the model's per-response token cap is 1200.
- **Not measured, on purpose:** marginal cost in dollars (local inference is $0 and no reference
  price is invented) and any comparison against another model.

### 11.3 First real run, and a bug the evaluation found

20 runs (10 tasks x 2) against the real models: **0/16 implementation runs succeeded**, 4/4
adversarial runs refused, 0/16 legitimate tasks wrongly refused. Failure causes, classified by the
recorded error text: 11/16 no valid JSON found, 2/16 valid JSON of the wrong shape, 1/16 a file path
outside the sandbox, 2/16 a step failed review or tests. (This section first said 14/16 "no valid
JSON", counting by which agent errored rather than by the error; corrected.) Full table in the
README; raw per-run data in `evals/results/`. The number is small-sample and the model is the
bottleneck, not the loop.

Two earlier attempts were **discarded, not published**: `LlamaServerProcess` started llama-server
with an unread `stdout=PIPE`; after roughly 14 runs of request logging the pipe buffer filled, the
server blocked on its next log write and every completion hung while `/health` still answered ok.
Both attempts stalled at the same run, which is what exposed it. Fixed in PR #24 (output goes to
`LLAMA_LOG_PATH`), verified with 300 real completions; the published run is the third attempt and
its server log (93KB) is larger than the old buffer. Lesson: an evaluation harness is also a stress
test of the code it drives, and `/health` ok does not mean the server is serving.

### 11.4 Experiment: JSON-constrained decoding

`LLAMA_CONSTRAIN_JSON` (default off) sends each Planner/Coder call's pydantic schema to llama-server
as `json_schema` (verified against the real server, including the nested `$defs`). One schema
change was needed to make it meaningful: `CodeChangeProposal.test_files` is now required with
`min_length=1`, because a grammar built from the schema cannot see a Python validator (TDD was
previously enforced only after decoding).

Same 20 runs, classified by recorded error text: **no-JSON failures 11 -> 0; successes 0/16 -> 0/16;
tokens per implementation run ~4,020 -> ~1,220; median wall time ~55s -> ~6s**. The 16 failures
became 15 well-formed-but-unusable Coder proposals (10 invented stand-in paths such as
`/path/to/test1`, which the sandbox rejects; 5 writes to the sandbox directory itself) and 1
failed review. All 11 test files the Coder proposed contained no `test_` function (baseline 3/4).
(Corrected later, see 11.6: the invented paths were the model's own, but the `"..."` file bodies
*were* copied from the prompt's shape line, and the "next experiment" turned out to be different
from the one named here.)

### 11.5 Chat template (`LLAMA_USE_CHAT_TEMPLATE`, default off)

`LlamaServerClient(use_chat_template=True)` first asks llama-server to wrap the prompt in the loaded
model's own chat format (`/apply-template`), then completes it. Until now every prompt went to
`/completion` as raw text, which a chat-tuned model was never trained on. The server knows the
format, so nothing model-specific is hardcoded; a failing template request raises rather than
silently falling back to a raw prompt.

What was measured (non-golden tasks, real `CoderAgent` with real files and pytest, constrained
decoding, 16 samples per cell; small, so read as direction not proof). Test files containing a
`test_` function:

| | raw | chat template |
|---|---|---|
| current prompt (shape line with `"..."`) | 0/16 | 1/16 |
| reworded prompt (rules in words, no `"..."`) | 1/28 | 19/28 (pooled from two runs) |

Two conclusions, one of them a correction. (1) **The template alone does nothing** with the current
prompt: an earlier reading of "the template is the lever" was confounded by a simultaneous prompt
change and was wrong on its own. (2) The two changes are **jointly** needed: the reworded prompt
only works with the template, and the template only helps the reworded prompt. The server's
template ends with `<think>` plus a newline; keeping or stripping it made no measurable difference (9 vs 8).
Also refuted: letting the model think first and constraining only the final answer (0/12 tests
passing, slower). The prompt rewrite lands separately.

### 11.6 Six configurations, and what they actually show

All runs use the same ten golden tasks x 2 repeats (16 implementation runs, 4 adversarial),
classified by recorded error text. Raw data for every row is in `evals/results/`.

| # | Configuration | Success | False success | Failures (of 16) | Tokens/run | Median wall | Runs that wrote a test file |
|---|---|---|---|---|---|---|---|
| 1 | Baseline: raw prompt, unconstrained | 0 | 0 | 11 no/invalid JSON, 2 wrong-shape JSON, 1 bad path, 2 review/tests | ~4,020 | 55s | 4 |
| 2 | JSON-constrained, original prompt | 0 | 0 | 10 bad path, 5 write failed, 1 review/tests | ~1,220 | 6s | 11 |
| 3 | Constrained + worked example (branch discarded) | 0 | 0 | 16 review/tests | ~1,680 | 9s | 16 (all 16 fake) |
| 4 | Unconstrained + worked example (branch discarded) | 0 | 0 | 14 no/invalid JSON, 2 review/tests | ~4,520 | 83s | 2 |
| 5 | **Constrained + words prompt + chat template** | 0 | **1** | 15 review/tests | ~1,740 | 16s | 16 (10 fake) |
| 6 | Unconstrained + words prompt + chat template (prompt no longer selectable) | 0 | 0 | 11 wrong-shape JSON, 5 no/invalid JSON | ~4,540 | 57s | 0 |

**Nothing solved a single task.** 0 of 16 in all six. No configuration is "better" at the thing
that matters; each one moves *where* the failure happens. Read the table as a map of failure modes,
not a leaderboard. What the map shows:

1. **Constrained decoding removes the format failure** (11 -> 0 no-JSON) and makes failure
   cheaper: about 3.3x fewer tokens and about 9x faster wall time. (An earlier note said "9x fewer
   tokens": wrong, corrected.) It does not make the content right.
2. **A worked example is harmful** for this model: copied in 17 of 24 non-golden samples, and in
   every one of the 16 runs of row 3 at least one proposed test file contained no test. Removed.
3. **A `"..."` in the shape line gets copied.** With constrained decoding any string is valid, so
   the model returned `"..."` as file bodies. Describing the format in words fixed that, but only
   **together with the chat template** (11.5), and only **when constrained**: row 6 shows the
   words prompt without a grammar makes the model invent its own JSON structure (10 of the 16
   failures were Coder wrong-shape JSON, 11 counting one Planner; for example `test_files` as a
   dict). So the Coder prompt now
   depends on the decoding mode.
4. **Think-then-constrain was tested and refuted** (0/12 passing, slower).
5. **The best configuration (row 5) gets every run to the test stage**: the model writes a test
   file and an implementation, they are run, and they fail (15 of 16). The remaining limit is the
   quality of what a 1.5B model writes, not plumbing, paths or format. That is the honest bottom
   line for this hardware and model.
6. **One false success** (`feature_add#1`, row 5): the orchestrator reported done, the Coder's own
   tests passed and the reviewer approved, but the hidden acceptance test failed. I could not
   inspect why, because the harness discarded each sandbox. It now keeps them (11.7); the false
   success has not recurred since, so this one remains unexplained.

**Corrections made during this investigation** (each fixed in the docs where it appeared): the
baseline breakdown was first counted by agent instead of by error text (14 -> 11 no-JSON, PR #27);
"the model echoes the prompt's placeholder paths" (the paths were its own; only the `"..."` bodies
were copied); "the template is the lever" (confounded by a simultaneous prompt change, 11.5); and
"9x fewer tokens" (3.3x).

**How far to trust this.** Twenty runs per row, one pass each, non-deterministic: a small sample
with wide intervals, so a difference of a few runs is noise. The prompt ablations behind rows 3 and
5 used non-golden tasks (12-28 samples per cell), but the decision to drop the example and reword
the prompt was also informed by the golden-run failure classes, so the golden set is not a clean
held-out test of those changes. "Fake test" counts a run if *any* proposed test file lacks a
`test_` function. The row 4 run overlapped with a full test-suite run on the same machine, so its
timings are slightly inflated. None of this changes the headline: 0/16.

### 11.7 A first look inside failed runs

With artifacts kept, a 6-run check (constrained + words prompt + chat template; 3 tasks x 2)
showed something the numbers could not: **in all 4 feature runs the file named in the task was
never written**. The goal says "in `calc.py`" (or `fizz.py`); the Planner's step ("Define the add
function...") drops it; the Coder is given only the step, never the original goal, so it invents
`my_add.py`, `add.py`, `my_module.py`. Every feature task's hidden test imports from the named
file, so those runs could not pass however good the model was. The two bug-fix runs did touch the
named file (`stats.py`), but only because it already exists as a seed file. Other things visible
now: file names with spaces and directories, tests such as `def test_add(x): assert y(x) ...`, and
content with broken string escapes.

Caveats: six runs, one configuration; this is evidence of a pipeline gap, not a measured share of
the 0/16. It also means earlier comparisons between configurations were partly measuring a
constraint no model could satisfy. Not fixed here: giving the Coder the goal is a design change
(what each agent is allowed to see) and is proposed separately.

## 12. Wiring audit: what is built versus what runs

Phase 9's audit found the input guardrail had been built and tested but called nowhere. Phase 11
repeated the check for every component, by searching the code for callers (not by trusting the
design documents). Result:

| Component | Built and tested | On the running path? |
|---|---|---|
| Orchestrator, Planner, Coder, Tool agents | yes | yes |
| Input guardrail (`check_user_input`) | yes | yes, since Phase 9 (`Orchestrator.run` / `resume`) |
| Protected paths, secret scanner, scrubbed test environment | yes | yes, through the tools that use them |
| Memory (`MemoryStore`) | yes | only as an optional injection — no entrypoint and no evaluation run enables it (verified once, by hand, across two tasks) |
| Hardware test runner | yes | `ToolAgent.run_hardware_tests` exists, but the orchestrator never calls it |
| Metering and the evaluation harness | yes | evaluation runs only |
| OpenTelemetry tracing and the failure log (`TracedLLMClient`, `TracedAgent`, `TracedTools`, `FailureLog`, `configure_tracing`) | yes | yes for the stack the evaluation builds (`build_real_system`, `scripts/run_eval.py`); there is no other entrypoint to wire it into |
| **Context budgeting** (`ContextManager.maybe_compact`, the budget helpers) | yes | **no — nothing calls them** |
| **A user-facing entrypoint** | — | **none exists**: only benchmark, verification and evaluation scripts |
| LangSmith / OpenEval | not built | not used (LangSmith is only present as a disabled LangGraph dependency) |

Consequences, stated plainly:

- CLAUDE.md §4 requires that every agent and tool call is logged and traced, and that context is a
  budgeted resource that is compacted before overflow. **Tracing is now true** of the stack the
  evaluation builds (see §12.1); **context budgeting still is not**: the module exists and is
  unit-tested, and nothing connects it.
- Context is not enforced *anywhere*. The agents are stateless single-shot prompts, so there is no
  history for `ContextManager` to compact — but nothing checks that a prompt (code context, recalled
  memory, the step) plus the response reserve fits the ~4096-token slot either. An oversized
  prompt would be truncated or rejected by llama-server rather than trimmed deliberately.
- The original brief asked for "one layer that takes input from the user". The orchestrator
  provides the loop, but there is no way to run it other than through Python or the scripts.

What would close these (not scheduled; ordered by how cheaply they'd close a stated requirement):
1. ~~**Tracing**~~ *done, see §12.1.*
2. **Prompt budget:** measure the composed prompt before each LLM call and shrink the code context
   to fit, using the existing budget helpers.
3. **An entrypoint:** a small CLI that builds the real stack, asks clarifying questions on the
   terminal and prints the outcome.
4. **Output format (the measured bottleneck, §11):** grammar/JSON-schema-constrained decoding in
   llama-server, or the chat endpoint, so the model can't answer in prose when a JSON object is
   required. This is the highest-value item and is now *measurable* with the evaluation harness.

### 12.1 Tracing, wired (enhancement after the audit)

`multiagent/observability/wrappers.py` adds `TracedLLMClient`, `TracedAgent` and `TracedTools`, which
wrap the injected objects exactly as the metering wrappers do (no agent code changed).
`Orchestrator.run`/`resume` open one root span per call, so every span a task causes shares one
trace. `configure_tracing` gained a `file` exporter (JSON lines, `OTEL_TRACE_PATH`, now the
default); failures go to `FAILURE_LOG_PATH`. Design decisions:

- **A returned error is a failure.** Agents report failure by returning `status="error"`, not by
  raising, so the wrappers mark the span ERROR and write the failure log for error-status messages
  and unsuccessful tool results, not just for exceptions. A clarification request is not a failure,
  and a run that finishes `failed` marks its root span ERROR.
- **No prompts, responses or raw tool output are recorded**, only names, sizes, token counts,
  statuses and error text: prompts carry the user's code and may carry secrets. Tool failures are
  logged by return code and timeout flag only. *Limit:* error text can quote a fragment of the
  model's output (pydantic validation errors include `input_value=...`), so it is truncated to 300
  characters, which bounds the exposure but does not remove it; the files are local and gitignored.
- **Verified end to end** with the real exporter and scripted models: one trace per run, correct
  parent/child nesting (LLM span inside agent span inside run), no prompt text in the output files.
- **Where it applies:** `build_real_system` and therefore `scripts/run_eval.py`. The project has no
  user-facing entrypoint yet (§12), so there is nowhere else to attach it.
