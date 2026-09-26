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
   - be given the original goal as well as its step (a step can drop details the goal carries,
     such as the file name),
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
    is free, so token counts stand in for cost) — recorded per run under `evals/results/`.

## 2. Non-functional requirements

- **Local-first, zero paid dependency.** The core loop must run with no internet access beyond
  optional GitHub operations and no paid API keys.
- **Hardware headroom.** Combined CPU/GPU utilisation must be designed to avoid sustained 85%+
  usage on either resource (see §3) — this laptop is used for other things.
- **Least privilege.** No sub-agent has more tool access than its role strictly requires.
- **Determinism where it matters.** Retry counts, step budgets, and the plan→execute→review loop
  are deterministic Python control flow, not left to LLM judgement.
- **Testability.** Every component must be unit-testable with a stubbed LLM client, independent
  of whether Ollama (or `llama-server`) is actually running.
- **File size discipline.** No source file over ~400 lines.

## 3. Hardware & local inference design

Measured specs and the decisions derived from them are in
[TRACKER.md](TRACKER.md#1-decisions-log) (decisions D3-D5 and D8).

The Planner, Coder and Tool agent run on Ollama `qwen2.5:7b-instruct` (7.6B parameters, Q4_K_M,
4.7GB, 32K native context). It does not fit the laptop's 4GB of VRAM, so Ollama splits it between
GPU and CPU. **Measured on this machine (2026-09-26, 4096-token context, 120 generated tokens):**
about 7.9 tokens/s, 5.1GB resident, 55% CPU / 45% GPU as reported by `ollama ps`. A large share of
the work therefore runs on the CPU, which keeps the processor busy: long evaluation runs should
not overlap with other work on the laptop (§2, hardware headroom).

All three agents share **one Ollama client** (same GPU and context options), because different
options per agent would make Ollama reload the whole model each time the agents alternate. The
evaluation script exposes it as `--agent-model`, `--agent-context` (default 8192) and
`--agent-timeout` (default 900s: at this speed a long reply takes minutes, far past a default HTTP
timeout). Ollama also serves `nomic-embed-text` for the memory layer (§9).

**Optional backend: `llama-server` (llama.cpp).** `multiagent/llm/llama_server.py` builds and
supervises a `llama-server` process from settings (GPU layers, context size, parallel slots,
flash attention, KV-cache type, threads, log path) and `LlamaServerClient` talks to it. It was the
first backend, serving a 1.1GB 1.5B model fully on the GPU; that attempt failed the evaluation and
is recorded in [failed_experiment.md](failed_experiment.md).

All of the above are config values in `config/settings.py` or script flags, not hardcoded in agent
code, so the model or backend can be swapped without touching orchestration logic.

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
| Local LLM serving (all agents) | Ollama, `qwen2.5:7b-instruct`, GPU/CPU split | Already pulled |
| Optional backend | llama.cpp `llama-server` (`E:\LLMCPP`) | CUDA build already present |
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

**Why this is a requirement here, not a nice-to-have:** the usable context on this hardware is
small. The KV cache competes with the weights for 4GB of VRAM, and with the optional
`llama-server` backend an explicit `-np 2` splits the configured `-c 8192` context across two
slots (about 4096 tokens each). The Ollama evaluation uses a context of 8192 (`--agent-context`).
A multi-step plan-execute-review loop with tool output in it needs that budget managed, so
compaction is load-bearing, not optional headroom.

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

System-level limitations, independent of which model is plugged in. How well a particular model
does the job is what the evaluation (§11) measures; the record of the first model that failed it
is in [failed_experiment.md](failed_experiment.md).

- **Schema-valid does not mean correct.** The parsers validate the *shape* of a response. The
  Coder's schema requires at least one test file but not that it contains a test function, so a
  proposal can be well-formed and still verify nothing; the evaluation's "fake test" metric exists
  to measure exactly this.
- **A reviewer's approval is a signal, not proof.** With the first small model, a plainly stated
  mismatch between a step and the Coder's summary was still approved. The orchestrator therefore
  treats `tests_passed` as the primary, objective gate and acts on a review *rejection*, but does
  not treat an approval as evidence of correctness.
- **A returned error is a failure.** Agents report failure by returning `status="error"` rather
  than raising, and a failing test run is reported as data, not as a system error; the
  orchestrator's retry and escalation policy is built on those two facts.
- **The sandbox rejects path escapes before any write** (all-or-nothing validation). Verified
  against real, messy model output, not only contrived test cases: an accidental absolute-looking
  path was rejected with a clear error and nothing was written.
- **LLM jobs are scoped to what is reliable.** The Tool agent's only LLM task is a short
  natural-language commit message; every git/gh action is deterministic Python. This is a design
  decision, not a claim about any model.

## 9. Memory layer (Phase 8)

Local mem0 (`multiagent/memory/store.py`), wrapped in a small project-scoped `MemoryStore`.

- **No LLM, on purpose.** Memories are stored verbatim (`infer=False`); the mem0 config
  deliberately has no `llm` section. mem0's default fact-extraction step would send every memory
  through a model on hardware where model budget is the scarcest resource (§3), and the CPU-only
  7B would take ~20s+ per memory. Embeddings only: Ollama `nomic-embed-text` + an on-disk qdrant
  store. Measured live: storing 4 memories ~0.4s, recall ~0.02s, GPU memory +4 MiB — the
  embedder is effectively free next to the model itself.
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
  context, and whether the wrapper actually changes a model's behaviour is
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
5. Whether wrapping context "as data" changes a model's behaviour is unmeasured.
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

`scripts/run_eval.py` runs the agents on an Ollama model (`--agent-model`, e.g.
`qwen2.5:7b-instruct`; without it the Planner and Coder use `llama-server` and the Tool agent uses
Ollama), then runs every golden task `--repeats` times (interleaved) through the **real** agent classes, sandboxed
filesystem and pytest runner, and **real git** against a throwaway repo with a *local bare remote*
— never GitHub. Results stream to `evals/results/<timestamp>.jsonl` as each run finishes, so an
interrupted run keeps what it has; the aggregate is rendered to `evals/results/<timestamp>.md`
and, with `--update-readme`, can be published into a marked section of the README.

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
  price is invented).

### 11.3 Optional generation controls

- **JSON-constrained decoding** (`LLAMA_CONSTRAIN_JSON`, default off; `--constrain-json` on the
  eval script): each Planner/Coder call's pydantic schema is sent to the backend (`json_schema`
  for llama-server, `format` for Ollama) so the response must fit it. A grammar built from the
  schema cannot see a Python validator, so rules that matter live in the schema itself:
  `CodeChangeProposal.test_files` is required with `min_length=1`. Verified against a real
  llama-server (including nested `$defs`); the Ollama `format` path is only unit-tested against a
  mock so far. llama.cpp honoured `maxItems` in a probe (a step cap in the plan schema) but did
  not appear to enforce `pattern`.
- **Mode-dependent Coder prompt:** when constrained, the format is described in words; when
  unconstrained, the explicit JSON shape is kept. Measured on the first small model: a
  placeholder-shaped line is copied literally under a grammar, and a words-only prompt without a
  grammar produces shapes the parser cannot read (details in failed_experiment.md).
- **Chat template** (`LLAMA_USE_CHAT_TEMPLATE`, default off, llama-server only):
  `LlamaServerClient(use_chat_template=True)` asks the server to wrap each prompt in the loaded
  model's own chat format (`/apply-template`) before completing it; a failed template request
  raises rather than silently sending a raw prompt. Ollama applies its models' templates itself.
- **The Coder is given the original goal** as well as its step (`implement_step(step,
  code_context, goal)`): a step can drop details the goal carries, such as the file name. It is
  the same text the Planner sees, including clarification answers; the Coder gains no new tool
  access, only more of the user's own task text, which already passed the input guardrail.

### 11.4 Results of earlier attempts

The evaluation of the first local model (a 1.5B-parameter reasoning model on `llama-server`) and
everything tried to rescue it are recorded in [failed_experiment.md](failed_experiment.md), which
also holds the measurements that used to live in this section.

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
  memory, the step) plus the response reserve fits the model's context window either. An oversized
  prompt would be truncated or rejected by the backend rather than trimmed deliberately.
- The original brief asked for "one layer that takes input from the user". The orchestrator
  provides the loop, but there is no way to run it other than through Python or the scripts.

What would close these (not scheduled; ordered by how cheaply they'd close a stated requirement):
1. ~~**Tracing**~~ *done, see §12.1.*
2. **Prompt budget:** measure the composed prompt before each LLM call and shrink the code context
   to fit, using the existing budget helpers.
3. **An entrypoint:** a small CLI that builds the real stack, asks clarifying questions on the
   terminal and prints the outcome.
4. ~~**Output format**~~ *done: optional JSON-schema-constrained decoding and chat template, §11.3.*

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
