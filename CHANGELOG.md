# Changelog

One entry per phase, newest last, with the PRs that delivered it and the most important thing each
phase *taught* (not just what it added). Full detail and the decisions log are in
[TRACKER.md](TRACKER.md); measured limitations are in
[REQUIREMENTS.md §8](REQUIREMENTS.md#8-known-limitations-measured-not-assumed).

## Phase 0 — Scaffolding
Governance docs, single-source settings, first tests, GitHub repo. Committed directly to `main`
(there was no base branch to open a PR against yet).

## Phase 1 — Local model serving · #1
Tuned `llama-server` launcher and a CPU-only Ollama client. *Learned:* the 1.5B model fits the 4GB
GPU with room to spare (~1.2GB), so the CPU-KV-cache split was unnecessary; CPU-only 7B generates at
~1.4 tok/s.

## Phase 2 — Shared infrastructure · #2 #3 #4
Strict `AgentMessage` contract, OpenTelemetry tracing, input/tool-output guardrails.
*Later found:* the tracing and the input guardrail were built here but never wired into the running
system (see Phases 9 and 11).

## Phase 3 — Context engineering · #5
Token-budget tracking and compaction. *Learned:* `llama-server -np 2` splits the context per slot,
so each agent really gets ~4096 tokens, not 8192. *Later found:* nothing calls it (Phase 11).

## Phase 4 — Planning agent · #6 #7
Read-only filesystem tool, prompt, response parser, `PlannerAgent`. *Learned:* the naive greedy
brace-match parser matched an unrelated fragment; the reasoning model sometimes ignores "JSON only"
entirely — the limitation that later dominates the evaluation.

## Phase 5 — Coding agent · #8 #9 #10
Writable filesystem, sandboxed pytest runner, `CoderAgent`. *Learned:* TDD is enforced structurally
but only checks a test file *exists*; a Windows newline-translation bug was caught by a test first.

## Phase 6 — Tool agent · #11 #12 #13
Allowlisted git/gh, bounded retry + circuit breaker, best-effort hardware runner. *Learned:*
narrowing the LLM's job to a short natural-language string (a commit message) made even the CPU-only
model reliable.

## Phase 7 — Orchestrator · #14 #15
LangGraph loop with human-in-the-loop clarification, bounded retries, hard step budget, and the
Planner's review gate. *Learned:* the review gate rubber-stamped an explicit description/summary
mismatch, so `tests_passed` is the primary gate; planning failures initially had zero retries (caught
by a live run, not the unit tests).

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

## Phase 10 — Evaluation · #22 #23
Wilson intervals, metering, ten golden tasks with hidden acceptance tests validated by real pytest
runs, a runner, a report, and a real-model run (results in the README). *Learned:* see the README's
Evaluation section — the dominant failure is the model not producing the required JSON.

## Phase 11 — Polish and a wiring audit
Diagram redrawn to distinguish what is wired from what is merely built; README claims corrected
(LangSmith/OpenEval are not used; the intro no longer promises a *merged* PR); this changelog; and a
component-by-component wiring audit (REQUIREMENTS.md §12) that found tracing and context budgeting
built but unconnected and no user-facing entrypoint. *Learned:* "built and unit-tested" is not the
same as "part of the running system" — the same lesson Phase 9 taught, one layer wider.
