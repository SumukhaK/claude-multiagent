# Claude Multiagent — What This Project Is (Plain English)

## The idea

This project is a small team of AI "workers" that cooperate to write and fix code, the way a
tiny software team would — but the whole team is AI, and it runs on a personal laptop instead
of in the cloud.

Instead of one AI trying to do everything at once (understand the request, plan it, write the
code, test it, and push it to GitHub), the work is split between three specialists:

- **The Planner** — thinks about the request first. Reads the existing code, asks questions if
  anything is unclear, thinks through what could go wrong, and writes a step-by-step plan.
- **The Coder** — follows the plan one step at a time. Writes a test for each piece of code
  *before* writing the code itself, so there's proof it actually works.
- **The Tool agent** — handles everything outside the code itself: creating branches, committing,
  opening pull requests on GitHub, and running any tests that need real hardware.

A fourth piece, the **Orchestrator**, is the "project manager" — it passes work between the three
specialists in a fixed order (plan → code → review → next step), checks each step actually
succeeded before moving on, and knows when to give up and ask the human instead of getting stuck
in a loop.

## Why split it up like this?

- **Safety**: each AI worker only gets the tools it actually needs. The Coder can edit files but
  can't push to GitHub. The Tool agent can push to GitHub but can't edit code. That way, if
  anything goes wrong, the damage it could do is limited.
- **Quality**: because the Planner reviews the Coder's work before the next step starts, mistakes
  get caught early instead of piling up.
- **Honesty**: nothing is invented. If the AI isn't sure what's being asked, it stops and asks
  instead of guessing.

## Why does it run locally instead of using ChatGPT-style cloud AI?

The models run directly on this laptop's own hardware (its graphics card and processor), so
there's no subscription, no per-request cost, and no sending code to a third party. The trade-off
is that local models are smaller and less powerful than the biggest cloud models — which is why a
lot of engineering effort goes into running them as efficiently as possible on modest hardware
(a laptop graphics card with only 4GB of memory), and into giving the AI workers a very
structured, disciplined process so a smaller model can still do reliable work.

## What "done" looks like

A working system where you can describe a coding task in plain language, the Planner asks any
necessary questions and lays out a plan, the Coder implements it with tests, and the Tool agent
ships it to GitHub as a reviewed pull request — with a report card at the end showing how well
the whole system performed (how fast, how much it "thought", how often it succeeded on the first
try, and how often it made something up and caught its own mistake).

## Who this is for

This is a portfolio project demonstrating practical AI engineering — not a commercial product,
and not something being hosted for other people to use.
