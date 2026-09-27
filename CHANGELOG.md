# Changelog

One entry per phase, newest last, with the PRs that delivered it and the most important thing each
phase *taught* (not just what it added). Full detail and the decisions log are in
[TRACKER.md](TRACKER.md); measured limitations are in
[REQUIREMENTS.md §8](REQUIREMENTS.md#8-known-limitations-measured-not-assumed).

## Phase 0 — Scaffolding
Governance docs, single-source settings, first tests, GitHub repo. Committed directly to `main`
(there was no base branch to open a PR against yet).

## Phase 1 — Local model serving · #1
A `llama-server` launcher and an Ollama client behind a shared `LLMClient` interface.

## Phase 2 — Shared infrastructure · #2 #3 #4
Strict `AgentMessage` contract, OpenTelemetry tracing, input/tool-output guardrails.
*Later found:* the tracing and the input guardrail were built here but never wired into the running
system (see Phases 9 and 11).

## Phase 3 — Context engineering · #5
Token-budget tracking and compaction. *Later found:* nothing calls it (Phase 11).

## Phase 4 — Planning agent · #6 #7
Read-only filesystem tool, prompt, response parser, `PlannerAgent`. *Learned:* the naive greedy
brace-match parser matched an unrelated fragment, so the parser was rebuilt around a balanced-brace
scanner.

## Phase 5 — Coding agent · #8 #9 #10
Writable filesystem, sandboxed pytest runner, `CoderAgent`. *Learned:* TDD is enforced structurally
but only checks a test file *exists*; a Windows newline-translation bug was caught by a test first.

## Phase 6 — Tool agent · #11 #12 #13
Allowlisted git/gh, bounded retry + circuit breaker, best-effort hardware runner. *Learned:*
narrowing the LLM's job to a short natural-language string (a commit message) kept that step simple.

## Phase 7 — Orchestrator · #14 #15
LangGraph loop with human-in-the-loop clarification, bounded retries, hard step budget, and the
Planner's review gate. *Learned:* a reviewer's approval is not a trustworthy hard gate, so
`tests_passed` is the primary gate; planning failures initially had zero retries (caught by a live
run, not the unit tests).

## Phase 8 — Memory layer · #16 #17
Local mem0 (Ollama embeddings, on-disk store, no LLM, telemetry off), wired into the orchestrator.
*Learned:* local qdrant allows one client per folder; a hypothesis (nomic task prefixes help) was
tested and rejected.

## Phase 9 — Security hardening · #18 #19 #20 #21
Protected paths, outbound secret scanning, `git add` hardening, the input guardrail wired in and
rebuilt against a corpus, scrubbed environment for model-written tests. *Learned:* the Planner could
read `.env`; the old input filter blocked 4 of 25 attacks yet refused 3 of 24 legitimate requests;
and the Coder executes model-written code with the developer's full OS privileges — which
contradicted a claim in CLAUDE.md, now corrected.

## Phase 10 — Evaluation · #22 #23 #25 (+ #24)
Wilson intervals, metering, ten golden tasks with hidden acceptance tests validated by real pytest
runs, a runner and a report. *Learned:* the evaluation itself exposed a bug in the llama-server
wrapper (an unread stdout pipe froze the server after ~14 runs while `/health` still said ok),
fixed in #24.

## Phase 11 — Polish and a wiring audit
Diagram redrawn to distinguish what is wired from what is merely built; README claims corrected
(LangSmith/OpenEval are not used; the intro no longer promises a *merged* PR); this changelog; and a
component-by-component wiring audit (REQUIREMENTS.md §12) that found tracing and context budgeting
built but unconnected and no user-facing entrypoint. *Learned:* "built and unit-tested" is not the
same as "part of the running system" — the same lesson Phase 9 taught, one layer wider.

## After Phase 11 — enhancements · #27 #28 #29 #30 #31 #33 #34
Optional JSON-schema-constrained decoding (#28), tracing wired into the evaluation stack (#29), an
optional chat template (#30), a mode-dependent Coder prompt (#31), failure artifacts kept for every
run that does not succeed (#33), and the original goal handed to the Coder (#34). *Learned:* an
evaluation that discards its evidence cannot explain its own results, and inspecting that evidence
found a real pipeline bug (the Coder was never told the file name).

## The first local model, and moving to Qwen · #37
The first local model (1.5B parameters on `llama-server`) did not pass the golden set; the full
record, with plain-English explanations, is in [failed_experiment.md](failed_experiment.md). The
agents now run on Ollama `qwen2.5:7b-instruct`, which is the default backend in settings and in
the eval and benchmark scripts (`llama-server` stays as an optional backend); the same harness then
showed the hidden test passing in 11 of 16 implementation runs (0 of 16 before) while the system
still reported no successes, because its review gate, plan granularity and JSON parsing discard
correct work (failed_experiment.md section 8).

## The review gate
The reviewer now sees the code and the overall goal, approves unless it can name a concrete defect,
and its feedback reaches the Coder's retry. *Learned:* a reviewer that cannot see the evidence
rejects by deferring, and the old one rejected correct and buggy code at nearly the same rate, so
its rejections carried no information; measure a gate on both correct and wrong cases, not just on
how often it says no.

## The first successes
A full golden run on the fixed review gate produced 4 of 16 genuine successes (0 before). Checking
every remaining failure individually confirmed the reviewer was not the cause of any of them; the
Coder's own self-written tests now are, both by failing outright and by hiding two more successes
that had already landed on disk. *Learned:* fixing the measured bottleneck can reveal the next one
cleanly, if every failure is still checked rather than assumed to be the old cause.

## Measuring the retry-feedback fix
Still 4 of 16 successes, but malformed JSON dropped from 6 to 2 of 12 non-successes while the
Coder's own tests failing every retry rose from 4 to 10 and became the dominant cause, with zero
review rejections anywhere in the run. *Learned:* a fix can work exactly as built (the model is
now told precisely what's wrong, confirmed by inspecting a captured SyntaxError traceback) and
still not move the score, because sometimes the model cannot act on correct information within its
retry budget. That's a different, harder problem than the one that was fixed.
