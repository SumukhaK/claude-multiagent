# Failed experiment: a 1.5B local model as the Planner and Coder

**Verdict:** with `DeepSeek-R1-Distill-Qwen-1.5B` (Q4) as the Planner and Coder, the multi-agent
system completed **0 of 16** implementation tasks in **every one of eight configurations** on the
golden set. This file records what the small model did that caused that, kept apart from the
failures that were my own bugs, and from what is still unproven.

Everything below is measured from saved runs (`evals/results/`) or from ablation probes, and
cross-referenced to [REQUIREMENTS.md](REQUIREMENTS.md) §11. Where a claim is an inference rather
than a measurement, it says so.

> **In plain English.** We asked a very small AI (1.5 billion "settings"; many of the popular
> assistants are far larger) to do junior-programmer work on a laptop: make a
> plan, write some code, write tests for it, and hand each piece to the next worker in a strict
> form. It mostly could not. It would not stick to the form, it copied the sample text instead of
> filling it in, it wrote tests that test nothing, and it made up file names. Along the way we found
> and fixed real mistakes in our own system, and each fix changed *how* it failed without ever
> letting a single task pass. Our best guess is that the model is simply too small for this job.
> That is a guess: we have not yet tried a bigger model to check.

Each failure below has a technical description followed by an **In plain English** line.

## 1. What was tried

- **Hardware:** Ryzen 7 4800H, 16GB RAM, GTX 1650 Ti with 4GB VRAM. The whole point was to run
  locally, free, without saturating the laptop.
- **Model:** `DeepSeek-R1-Distill-Qwen-1.5B-UD-Q4_K_XL.gguf` (1.1GB) on `llama-server`, fully on
  the GPU, serving both the Planner and the Coder. The Tool agent used Ollama `qwen2.5:7b-instruct`
  on CPU and worked fine, because its only model task is writing a one-line commit message.
- **Evaluation:** ten golden tasks (five features, two bug fixes, one underspecified task, two
  adversarial), two runs each, judged by a hidden acceptance test rather than by the model's word.

*In plain English:* a small, free AI running on one laptop, tested on ten small programming jobs,
each marked by a hidden answer key so the AI could not just claim it had succeeded.

## 2. The result, in one table

Failures counted by the recorded error text. "Test file runs" is how many of the 16 implementation
runs got as far as writing a test file.

| # | Configuration | Success | Main failures (of 16) | Test-file runs |
|---|---|---|---|---|
| 1 | Baseline (raw prompt, unconstrained) | 0 | 11 no valid JSON, 2 wrong-shape JSON, 2 review/tests, 1 bad path | 4 |
| 2 | JSON-constrained decoding | 0 | 10 bad path, 5 write failed, 1 review/tests | 11 |
| 3 | Constrained + worked example in prompt | 0 | 16 review/tests | 16 |
| 4 | Unconstrained + worked example | 0 | 14 no valid JSON, 2 review/tests | 2 |
| 5 | Constrained + reworded prompt + chat template | 0 (1 false success) | 15 review/tests | 16 |
| 6 | Unconstrained + reworded prompt + template | 0 | 11 wrong-shape JSON, 5 no valid JSON | 0 |
| 7 | Row 5 + original goal given to the Coder | 0 | 13 review/tests, 3 no valid JSON | 15 |
| 8 | Default + goal given to the Coder | 0 | 6 no JSON, 5 wrong-shape, 3 bad path, 1 review, 1 empty plan | 5 |

Every fix moved *where* the failure happens. None moved the success count off zero.

*In plain English:* we tried eight different setups. In the early ones the AI could not even
produce something the system could read. In the later ones it produced readable work, wrote code
and tests, and the tests still failed. Zero tasks passed in any of them.

## 3. What the small model did (the failures attributed to it)

These are observed behaviours, each seen in saved output, all at the 1.5B scale. Whether a larger
model avoids them is exactly what has not been tested yet (section 5).

1. **It ignores "reply with JSON only".** Unconstrained, it answered in prose or unfinished JSON
   in 11 of 16 baseline runs (14 of 16 with the worked-example prompt). The Planner also failed
   this way on its own.

   *In plain English:* like asking someone to fill in a form and getting a friendly letter back
   instead. The next worker in the chain can only read forms, not letters, so the whole task
   stopped there.

2. **When not shown an exact shape, it invents its own JSON structure.** With the format described
   in words and no grammar (row 6), 10 of 16 runs failed with JSON of the wrong shape, for example
   `test_files` as a dictionary keyed by file name, or a key called `"relative"`.

   *In plain English:* given loose instructions instead of a blank form to copy, it drew up its
   own form layout, and the system did not recognise it.

3. **It copies placeholders literally.** Shown `"content": "..."`, it returned `"..."` as the file
   body (constrained mode allows any string). It copied `<restate the goal>` into a plan's
   `goal`. It copied a worked example verbatim in 17 of 24 samples, leaking `shout` and `"HI!"`
   into unrelated tasks.

   *In plain English:* shown a form with "..." in the boxes, it wrote "..." in the boxes. Shown a
   worked example, it handed in the example's answer for a completely different question.

4. **Under a grammar its text degenerates.** Real outputs included runaway strings
   (`numbers_test_1000000000...`), rambling sentences inside a JSON string
   (`"...}},...}: each key in step_files is a list of objects..."`), and broken string escapes.

   *In plain English:* when we forced it to stay strictly inside the form, it sometimes got stuck
   like a scratched record, repeating "0000000..." or rambling on inside a single box.

5. **It writes junk tests.** `def test_add(x): assert y(x) ...` is a real output. Test files with
   no test function appeared in 10 of 16 runs even in the best configuration (16 of 16 before the
   prompt was reworded). It put implementation code in `test_files` and test code in
   implementation files.

   *In plain English:* the "tests" it wrote did not test anything real, like a fire-drill checklist
   with no fire drill in it. Sometimes it put the answer sheet where the test sheet belonged.

6. **It invents file names and structure.** `my_add.py`, `add.py`, `my_module.py`, file names with
   spaces (`test average.py`), directories, and, in constrained mode, absolute-looking paths such
   as `/path/to/test1` (10 of 16 runs, before the prompt was reworded).

   *In plain English:* told to save its work as `calc.py`, it saved it as `my_add.py`, so the
   answer key went looking for `calc.py` and found nothing. Paths like `/path/to/test1` were the
   sample text from the instructions, used as if it were real.

7. **It only partly follows an instruction it is given.** Even after the original goal (which names
   the file) was handed to the Coder, the named file was written in only 2 to 3 of 10 feature
   runs.

   *In plain English:* even once we made sure it knew the right file name, it used that name in
   only a few of the tasks.

8. **It over-splits plans.** Planner plans average 3.4 steps (up to 7) for one-function tasks. A
   "small tasks are ONE step" rule was followed 1 time in 24. Each extra step is another Coder call
   that must add its own test file.

   *In plain English:* asked for a plan to make a cup of tea, it wrote a six-step plan. Every step
   needs its own check, so more steps meant more chances to slip up.

9. **When it does write correct code, it still breaks the structure.** In `feature_safe_divide#1`
   the model wrote a correct `safe_divide` into the right file (the hidden test passes 3 of 3), but
   put that file in `test_files` and sent later proposals with no test file, so the mandatory-TDD
   rule failed the step. The only run that produced correct code was still a failure.

   *In plain English:* it got the answer right but wrote it on the wrong page of the form, so the
   whole thing was marked as failed. That strict rule ("tests come first") is deliberate and stays.

10. **It is brittle to formatting.** Test files containing a test function, on non-golden tasks:
    0 of 16 with raw text and the original prompt, 1 of 16 with the chat template alone, 1 of 28
    with a reworded prompt alone, and about 19 of 28 with both together (and the reworded prompt
    made unconstrained runs worse). Small changes in prompt format swung results more than any
    real improvement in the system did.

    *In plain English:* tiny changes in how we worded or laid out the instructions changed the
    results enormously, like a student who passes a test when a question is phrased one way and
    fails when the same question is phrased another way. That kind of sensitivity makes a model
    hard to build on.

11. **A reasoning model without its reasoning.** Constrained decoding forces the answer from the
    first token, so the `<think>` phase never happens. Letting it think first and constraining only
    the final answer was tried and was no better (0 of 12 passing, slower).

    *In plain English:* this model is trained to think out loud before answering. Forcing a strict
    answer format skipped the thinking, like asking for the final answer with no scratch paper.
    Giving it the scratch paper back did not help either.

12. **One run was reported "done" while the hidden test failed** (the only false success, in
    row 5). It never recurred in later runs and remains unexplained.

    *In plain English:* once the system announced "finished" and the answer key said "wrong". We
    do not know why. It has not happened again.

13. **Cost.** Unconstrained runs used about 4,000 to 4,500 generated tokens each and 55 to 83
    seconds per task, mostly spent on output that was thrown away.

    *In plain English:* it wrote thousands of words per task, and most of them were unusable.

## 4. What was NOT the model (my own bugs, found and fixed)

Listed so the model is not blamed for them. Each was found by inspecting failures.

- The `llama-server` wrapper read its output through a pipe nobody drained, which froze the server
  after about 14 runs while `/health` still said OK (two evaluation attempts were discarded).
  *In plain English:* a sink with no drain: it slowly filled up and everything froze.
- Prompts were sent as raw text, without the model's chat format.
  *In plain English:* we were talking to the model without the conversation format it was trained
  to expect.
- The Coder was never told the original goal, so the file named in a task was not written in 4 of
  4 feature runs checked.
  *In plain English:* we handed the coder only "step 1" and never the overall job, so it did not
  know what to call the file.
- A worked example I added made things worse (see 3.3).
  *In plain English:* my own bad idea; the model copied the example instead of learning from it.
- The evaluation harness threw away every failed run's evidence.
  *In plain English:* we were clearing away the crime scene before looking at it.
- Two of my own explanations were wrong and were corrected (the failure breakdown was counted by
  agent instead of by error, and "the chat template alone is the fix" was confounded).
  *In plain English:* I sometimes blamed the wrong thing, and had to take it back.

## 5. What is not known

- **That the model is the cause is an inference by elimination, not a test.** I never ran this
  system with a stronger model. Four pipeline bugs were found by reading failures, so a fifth may
  exist.
- A stronger model could also hide a poorly designed pipeline, so a success would not prove the
  design right either.
- Samples are small (20 runs per configuration, one pass, non-deterministic; ablations of 12 to
  28 samples). Differences of a few runs are noise. The only firm result is the 0 of 16.

*In plain English:* it is like a car that will not start. We replaced four broken parts and it
still will not start, so we suspect the engine, but we have not swapped the engine to find out.
Swapping in a bigger model is that test.

## 6. What was decided

- **Not pursued:** pulling a further coder-tuned 7B model (`qwen2.5-coder:7b`), on the reasoning
  that an unknown gain is not worth the time; and rewording the Planner prompt (measured, made
  plans worse; REQUIREMENTS §11.8).
- **Next test:** run the identical harness with `qwen2.5:7b-instruct`, already installed (7.9
  tokens/s here with the GPU/CPU split), to separate "small model" from "system bug".

## 7. Where the evidence is

- Raw per-run results: `evals/results/*.jsonl` (eight result pairs for the configurations above).
- The full table, caveats and corrections: [REQUIREMENTS.md](REQUIREMENTS.md) §11.3 to §11.8.
- A chronological account: [TRACKER.md](TRACKER.md) and [CHANGELOG.md](CHANGELOG.md).
