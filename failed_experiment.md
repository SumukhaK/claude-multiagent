# Failed experiment: a 1.5B local model as the Planner and Coder

**Verdict:** with `DeepSeek-R1-Distill-Qwen-1.5B` (Q4) as the Planner and Coder, the multi-agent
system completed **0 of 16** implementation tasks in **every one of eight configurations** on the
golden set. This file records what the small model did that caused that, kept apart from the
failures that were my own bugs, and from what is still unproven.

Everything below is measured from saved runs (`evals/results/`) or from ablation probes; the
detailed measurements are in the appendix at the end. Where a claim is an inference rather than a
measurement, it says so.

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

- **Update: the test was run (section 8).** That the model was the cause was first only an
  inference by elimination. With `qwen2.5:7b-instruct` in the same system, the hidden acceptance
  test passed in 11 of 16 implementation runs, against 0 of 16 here, so model size was the main
  cause of the failures in section 3.
- A stronger model also exposed problems in the pipeline that the small model had hidden
  (section 8), so a better model alone does not make the system succeed.
- Samples are small (20 runs per configuration, one pass, non-deterministic; ablations of 12 to
  28 samples). Differences of a few runs are noise. The only firm result is the 0 of 16.

*In plain English:* it was like a car that would not start. We replaced four broken parts and it
still would not start, so we suspected the engine. We have now swapped the engine and the car runs,
which confirms the engine was the main fault, and shows a second, smaller fault elsewhere in the
car (section 8).

## 6. What was decided

- **Not pursued:** pulling a further coder-tuned 7B model (`qwen2.5-coder:7b`), on the reasoning
  that an unknown gain is not worth the time; and rewording the Planner prompt (measured, made
  plans worse; REQUIREMENTS §11.8).
- **Next test (done, section 8):** run the identical harness with `qwen2.5:7b-instruct`, already
  installed (about 8 tokens/s here with the GPU/CPU split), to separate "small model" from "system
  bug". It is now the default model.

## 7. Where the evidence is

- Raw per-run results: `evals/results/*.jsonl` (eight result pairs for the configurations above).
- The detailed measurements behind this document: the appendix below (they used to live in
  REQUIREMENTS.md §11, which now describes only the harness and the optional generation controls).
- A chronological account: [TRACKER.md](TRACKER.md) and [CHANGELOG.md](CHANGELOG.md).

## 8. Epilogue: the same system on a 7B model

After this record was written, the identical harness was run with `qwen2.5:7b-instruct` on Ollama
(7.6B parameters; result file `evals/results/20260926T184340Z`; 20 runs; no constrained decoding,
all other settings as before).

| | 1.5B model (best configuration, row 7) | 7B model |
|---|---|---|
| Hidden acceptance test passes | 0 of 16 | **11 of 16** |
| Orchestrator reports success | 0 of 16 | 0 of 16 |
| Tokens per implementation run | about 2,550 | about 2,320 |
| Median wall time | 19s | 147s |

So the model was the main problem: the code it writes is correct far more often than not. But the
system still counted **zero** successes, because it discarded correct work. Where the 16
implementation runs ended (from the saved raw responses and step reports):

| Runs | What happened |
|---|---|
| 7 | Correct code (the hidden test passes) and every review verdict was a rejection, so the run escalated |
| 2 | Correct code, but the Coder's own tests failed on every attempt, so the run escalated |
| 2 | Correct code (the hidden test passes), stopped by malformed JSON in the model's reply |
| 3 | Stopped by malformed JSON before the code was right (the hidden test fails) |
| 2 | Wrong code (the hidden test fails) |

The malformed-JSON stops are the model getting the escaping wrong when it puts code inside a JSON
string, in three forms seen in the saved responses: an unescaped quote ("Expecting ',' delimiter"),
a backslash escape JSON does not allow ("Invalid \escape"), and a raw newline inside a string
("Invalid control character"). The parser reports most of them as "no complete JSON object
found", because a stray quote breaks its scan for a balanced object. Several of these runs also
had earlier attempts that parsed fine. The reviews that rejected correct work
include a one-step plan whose step matched the task exactly, and plans cut into steps that cannot
be completed alone (for example "check if calc.py exists").

**Problems in the system, not the model (item 1 has since been addressed and confirmed, see
section 9):**
1. The review gate rejects correct work, including work that matches a one-step plan.
2. Plans are split into steps that cannot each be tested and completed on their own, and the
   reviewer judges the whole task against one narrow step.
3. Code embedded in JSON strings is fragile: the model sometimes leaves quotes, backslashes or
   newlines unescaped, and the parser rejects the whole reply instead of repairing it. Not yet
   tried: JSON-schema-constrained decoding (the Ollama `format` path is still unverified), or
   sending code as fenced blocks instead of JSON strings.
4. The Coder's own tests can be wrong even when its implementation is right.

*In plain English:* with the bigger AI the answers are mostly right; the hidden answer key agreed
in 11 of 16 tasks. But the system's own "reviewer" kept rejecting good answers, and a few answers
were thrown away over formatting mistakes in the AI's reply, so the score the system reports is
still zero. The problem has moved from the AI to our own review process, which is fixable.

**Follow-up: the review gate (item 1).** The reviewer now sees the code and the overall goal, and
its feedback reaches the Coder's retry. Replaying the saved Coder attempts whose tests passed
through the old and new reviewer on the 7B model (ground truth: the hidden test on each attempt's
exact files): approval of correct code rose from 6 of 26 votes to 26 of 26. On 9 mutants of correct
code that pass the Coder's own tests but fail the hidden test, the new reviewer approved 6 of 27
votes against 5 of 27 for the old one. The old reviewer approved correct and buggy code at about
the same rate (23% against 19%), so its rejections carried no signal; the new one separates them
(100% against 22%) but lets some subtle bugs through.

Caveats: 16 implementation runs, one pass each and non-deterministic, so read the counts as a
pattern, not precise rates. "Every review verdict was a rejection" is read from the saved review
responses of each run.

## 9. The first real successes

A full golden run with the fixed review gate (`evals/results/20260927T053525Z`, otherwise the same
settings as section 8's run): **4 of 16 tasks succeeded** — the first genuine successes this project
has produced, one each for `feature_add`, `feature_safe_divide`, `feature_password_strength` and
`bugfix_average`. 1 of 16 was a false success. Every one of the remaining 11 escalations was checked
individually against its saved artifacts (raw model output, review verdicts, step reports), and
**none of them was the reviewer rejecting correct work** — the failure mode that caused 7 of 16
escalations in section 8 did not recur once.

| Cause (of the 12 non-successes) | Runs | Detail |
|---|---|---|
| Malformed JSON from the Coder | 6 | The same escaping bug as section 8 (item 3): unescaped quotes, disallowed backslash escapes, raw newlines in a JSON string |
| The Coder's own tests fail on every retry of a step | 4 | The step never reaches review (only a passing `tests_passed` triggers it); in 2 of these 4 the *hidden* test actually passed on the final files on disk, so a real success was sitting there but the run still escalated on the Coder's own (wrong) test |
| Step budget exceeded (12 steps) | 1 | `feature_add#1`: too many steps for the budget (item 2) |
| False success | 1 | `feature_password_strength#1`: the Coder's own tests passed and the reviewer approved both steps ("the code correctly implements the logic to check if the password has at least 8 characters"), but the hidden test checks requirements the step never covered (rejecting a password with no digit, or no letter); the reviewer judges against the step and the code it can see, not an unseen answer key, so this kind of miss is an expected limit of the rubric, not a defect in it |

So the largest remaining problem changed. It used to be the reviewer discarding correct work (item
1, now fixed). It is now **the Coder's own self-written tests** (item 4): they caused 4 escalations
outright and, in 2 more cases, hid a success that had already happened on disk. Malformed JSON
(item 3) is unchanged and now the joint-largest cause.

*In plain English:* the fix worked — the "reviewer" is no longer throwing away good work, and for
the first time the system actually finished four tasks correctly. Looking at exactly why the other
twelve failed, the reviewer was never the reason for a single one of them. The new biggest problem
is that the coding worker sometimes writes its own tests wrong, so a step that was actually correct
still gets marked as failed by its own broken test and never gets a second look.

Caveats: 20 runs, one pass, non-deterministic; a 25% success rate on this run says nothing precise
about the true rate, only that it is now measurably above zero. The false-success rate (1 of 16)
should be watched, not ignored, as the review gate gets looser over time.

## 10. Fixing the blind retries did not raise the score, but changed what breaks

Sections 8 and 9 found two retry paths that fed the Coder nothing about why its last attempt
failed: a malformed-JSON coder error, and the Coder's own tests failing (which never reaches
review, so it was never covered by the review-gate fix). Both were fixed the same way as the
review gate: feed the failure back (`evals/results/20260927T065105Z`, same settings as section 9).

| | Section 9's run | This run |
|---|---|---|
| Task success | 4/16 | 4/16 |
| False success | 1/16 | 0/16 |
| Malformed JSON | 6 of 12 non-successes | **2** of 12 |
| Coder's own tests fail every retry | 4 of 12 | **10** of 12 |

**The success rate did not move. The malformed-JSON fix worked; the other one exposed a harder
problem underneath it.** Every one of the 12 non-successes was checked individually again: **zero
were review rejections** (every review call in this run was an approval), confirming section 9's
finding held. All 10 "own tests fail" escalations are the Coder's own self-written test failing on
every attempt within a step, so the step never reaches review at all.

The feedback mechanism itself works as built: `bugfix_slugify-1`'s second attempt was fed a real
pytest traceback from the first, and in `feature_add-1` the captured `test_output` correctly showed
a Python `SyntaxError` (`def test_add()` — missing the colon) after the first attempt. **The model
often cannot act on that information within three retries** — `feature_add-1`'s third attempt was
still syntactically broken. Feeding back *what* went wrong is not the same as the model being able
to *fix* it; that is a code-generation reliability limit at this model size, not a plumbing gap.

A second, distinct cause showed up in the same forensic pass: `clarification_format_name-0`'s first
plan step was *"Understand the current structure and naming conventions of the names.py file"* —
not an actionable coding step. Forced to produce a test and implementation anyway, the Coder wrote
`with pytest.raises(AssertionError): format_name('John Doe')`, a test that expects the function to
fail on ordinary input. This is item 2 (plan granularity) from section 8, seen concretely rather
than inferred from step counts.

*In plain English:* the fix worked exactly as built — no more blind retries — and it visibly fixed
one whole category of failure (garbled JSON replies). It didn't raise the score, because the bigger
problem underneath was never about missing information: sometimes the model is told precisely what
is wrong with its code and still cannot fix it in the tries it gets, and sometimes the plan itself
hands it a step that was never codeable.

Caveats: 20 runs, one pass, non-deterministic; a shift from 6 to 2 and from 4 to 10 on a base of 12
is suggestive, not proof, on this sample size.

## 11. Three fixes, three runs, the same score -- and a new constraint appears

The syntax pre-check (`ast.parse()` before pytest, no orchestrator change) was measured the same
way (`evals/results/20260927T080834Z`, same settings). **Still 4 of 16.** It fired three times in
this run and worked exactly as built -- confirmed live, not inferred: `bugfix_average-0` got
`SyntaxError in test_stats.py, line 3: expected ':'` instantly, and `feature_fizzbuzz-0` caught two
separate syntax errors mid-task and recovered from both.

| Cause (of 12 non-successes) | After the review gate | After retry feedback | After the syntax pre-check |
|---|---|---|---|
| False success | 1 | 0 | 0 |
| Malformed/wrong-shape JSON | 6 | 2 | 5 |
| Own tests fail every retry | 4 | 10 | 4 |
| Genuine review rejection | 0 | 0 | **1** |
| Step budget exhausted | 1 | 0 | **2** |

"Own tests fail" roughly halved back down (10 to 4), consistent with the pre-check removing part
of what drove it up. Malformed JSON went back up (2 to 5); on this sample size that is plausibly
noise, not a traceable regression. **A genuine review rejection appeared for the first time**:
`clarification_format_name-1` -- *"the implementation only handles the list case correctly but
fails when name is a single str"* -- a real, correctly-caught edge-case bug, evidence the reviewer
is not simply rubber-stamping everything it sees.

**A new problem showed up: step-budget exhaustion on code that was working.**
`feature_fizzbuzz-0` and `feature_password_strength-1` both had the hidden test passing and
multiple genuine review approvals along the way, but ran out of the evaluation harness's 12-step
budget before finishing. Every retry (each syntax-error catch, each review round) consumes a step
of that same shared budget, and a multi-step plan doesn't leave much room for that. Three fixes in
a row have each individually worked as designed and each shifted *where* the failure happens,
without moving the count off 4 of 16 once. What's left points at two different things: the model's
own code-generation reliability (it is now told exactly what's wrong and still can't always fix it
within budget), and the Planner producing plans with more steps, or less actionable steps, than the
fixed step budget can afford.

*In plain English:* three separate, careful fixes in a row, each shown to work exactly as intended,
and the number of finished tasks hasn't moved once. What's left isn't a wiring bug anymore -- it's
the AI sometimes genuinely not being able to fix what it's told is wrong, and the planning worker
sometimes drawing up more steps than the system allows it to safely retry through.

Caveats: 20 runs, one pass, non-deterministic; three runs at exactly 4/16 is a pattern worth taking
seriously, not proof that the rate is precisely 25%.

## 12. Plan granularity is the first fix to move the score

Section 11 pointed at two different things: the model's own code-generation reliability, and the
Planner producing more steps (or less actionable ones) than the fixed step budget can afford. The
second is fixable without touching the model. An additive instruction was added to the unchanged
Planner prompt: use exactly one step for a simple task, and never propose a "review", "understand",
or "explore" step. This is deliberately narrower than the full-prompt reword tried on the 1.5B model
and rejected (Appendix F) -- that reword made plans worse by removing the one thing (a worked
example of a one-step plan) that was keeping steps short.

Measured before being written, on the real qwen2.5:7b model, 24 samples per variant on non-golden
goals: mean steps per plan 2.96 -> 1.0, single-step plans 25% -> 100%, non-actionable steps 5 -> 0,
parse rate unaffected (100% both). Checked separately against two genuinely compound goals
(independent functions in one task) to confirm the rule doesn't just cap every plan at one step
regardless of complexity: 3 of 6 samples still split into independent steps.

A full golden run (`evals/results/20260927T094919Z`) then measured it against the real system:

| Cause (of non-successes) | After syntax pre-check (4/16) | After the granularity rule (7/16) |
|---|---|---|
| Total non-successes | 12 | 9 |
| False success | 0 | 0 |
| Malformed/wrong-shape JSON | 5 | 3 |
| Own tests fail every retry | 4 | 6 |
| Genuine review rejection | 1 | 0 |
| Step budget exhausted | 2 | 0 |

**7 of 16 -- the first score movement across four fixes.** Every one of the 9 non-success runs had
a plan with exactly 1 step (checked directly against the raw artifacts, not inferred), confirming
the rule is working mechanically in production exactly as the ablation predicted. Step-budget
exhaustion, the new failure mode from section 11, dropped back to zero -- a 1-step plan cannot run
out of a 12-step budget the way a multi-step one can. What's left split cleanly into the same two
buckets as before: malformed JSON (3) and the Coder's own tests failing every retry with zero review
calls reached (6, no genuine review rejections this run).

*In plain English:* the first three fixes repaired how the system reacts to a failure, but did that
inside plans that averaged three steps, so there were more places to go wrong and a fixed retry
budget ran out faster. Shrinking the plan to the one step the task actually needs didn't change any
of that retry machinery -- it just gave it a smaller, more winnable problem to work on, and the
score moved for the first time as a result.

Caveats: 16 runs, one pass, non-deterministic; a jump from 4/16 to 7/16 after being flat across
three prior runs is a real signal on this sample, not a precise rate.

## 13. JSON-schema-constrained decoding closes the JSON-shape failures, and surfaces a false success

The remaining "malformed/wrong-shape JSON" failures were read directly from the raw model output
(not inferred): the model was writing multi-line code into a JSON string as literal, unescaped
newlines, and in two cases also dropped a closing bracket after a long code string. The project
already had a lever for exactly this -- `CONSTRAIN_JSON` compiles each schema into a grammar and
has Ollama's `format` field mask the token sampler so it can only produce schema-valid JSON -- but
it had never been measured on this model, and REQUIREMENTS.md section 11.3 flagged the Ollama
`format` path as unit-tested against a mock only. It was also the exact lever that, on the 1.5B
model (section 11 of the Appendix), fixed every JSON-shape failure while making the aggregate result
worse, because the content behind the now-valid JSON degraded into bad file paths and empty writes.

Before trusting a full golden run, both questions were checked against the real qwen2.5:7b server:
24 Planner/Coder samples using the exact three goals that produced malformed JSON in the granularity
run, plus 8 follow-up samples isolating the one failure that appeared. Result: 31 of 32 samples
produced schema-valid JSON (not the theoretical 100% a grammar promises -- a real, if rare, residual
failure rate), the one miss was not `max_tokens` truncation (completion length nowhere near the
budget on retry), and every successful sample had sane file paths and non-empty implementation
content -- no sign of the 1.5B model's degradation.

A full golden run (`evals/results/20260927T143255Z`, `--constrain-json` added on top of the
granularity rule) then measured it against the real system:

| Cause (of non-successes) | After the granularity rule (7/16) | + constrained decoding (11/16) |
|---|---|---|
| Total non-successes | 9 | 5 |
| False success | 0 | 1 |
| Malformed/wrong-shape JSON | 3 | 0 |
| Own tests fail every retry | 6 | 4 |
| Genuine review rejection | 0 | 0 |
| Step budget exhausted | 0 | 0 |

**11 of 16 (69%) -- malformed JSON dropped to zero, exactly as the pre-run verification predicted,**
with no sign of the old content-quality trade-off.

**One result needs its own honest accounting: `clarification_format_name-1` came back `false_success`
-- the orchestrator reported `done`, and the hidden acceptance test failed.** Traced against the raw
artifacts: the task is deliberately ambiguous ("format a person's name") specifically to test whether
the Planner asks a clarifying question instead of guessing. It didn't -- it silently planned a
`{first_name, last_name}` dict shape. The Coder then wrote tests and an implementation that both
matched that same guess, so they passed each other, and the Planner's review approved a
self-consistent but wrong answer ("tests pass as expected"). Nothing in the loop ever checks a
guess against the real hidden test -- by design, the same way a human wouldn't have the answer key
mid-task. **This is not something constrained decoding caused.** "Clarifying question asked on the
underspecified task" has been 0 of 2 in every golden run measured so far, including this one and the
44% run before it; what changed here is that the Coder's guessed tests happened to be internally
consistent with its own guessed implementation, so nothing caught the mismatch. In the prior run the
same kind of guess produced self-contradictory tests instead, which escalated honestly rather than
reporting false success -- a difference in luck, not in the underlying gap.

One of the remaining four non-successes is worth naming for the same reason: `feature_safe_divide-0`
had the hidden acceptance test pass, but still escalated, because the Coder's own test asserted both
`safe_divide('10', 2) is None` and `pytest.raises(TypeError)` for `safe_divide('10', '2')` in the
same file -- two different, contradictory requirements for non-numeric input. No implementation can
satisfy both, so its own tests failed against every attempt regardless of correctness.

*In plain English:* telling the model's sampler it can only produce valid JSON worked -- the
shape-level failures that were left are gone, and nothing about the underlying code got worse to buy
that. But the false success is a reminder that fixing how reliably the system *says* something
doesn't fix whether what it says is *true* -- that gap was already there (the Planner has never once
asked the clarifying question this project's own test task is designed to require), constrained
decoding just wasn't what exposed it before.

Caveats: 16 runs, one pass, non-deterministic; a single false success on this sample size does not
establish a rate, but the underlying cause (0 of 2 clarifying questions asked, in every run so far)
is not new and is worth treating as a real, repeated finding rather than this run's noise.

---

## Appendix: the measurements behind this document

Moved here from REQUIREMENTS.md §11 so the requirements describe the system, not the failed model.
All figures are from ten golden tasks x 2 repeats (16 implementation runs, 4 adversarial), classified
by the recorded error text, unless stated otherwise.

### A. Which result file is which row of section 2

| Row | Result file (`evals/results/`) |
|---|---|
| 1 Baseline | `20260926T133225Z` |
| 2 Constrained | `20260926T135847Z` |
| 3 Constrained + worked example | `20260926T142432Z` |
| 4 Unconstrained + worked example | `20260926T142816Z` |
| 5 Constrained + reworded prompt + template | `20260926T170626Z` |
| 6 Unconstrained + reworded prompt + template | `20260926T171156Z` |
| 7 Row 5 + goal to the Coder | `20260926T175229Z` |
| 8 Default + goal to the Coder | `20260926T175935Z` |

Token and time figures per implementation run: row 1 about 4,020 tokens and 55s; row 2 about 1,220
and 6s; row 3 about 1,680 and 9s; row 4 about 4,520 and 83s; row 5 about 1,740 and 16s; row 6 about
4,540 and 57s; row 7 about 2,550 and 19s; row 8 about 3,510 and 37s (median wall clock). The row 4
run overlapped with a full test-suite run on the same machine, so its timings are slightly inflated.

### B. Constrained decoding against the baseline (rows 1 and 2)

| | Baseline | Constrained |
|---|---|---|
| Task success | 0/16 | 0/16 |
| Failed with no valid JSON | 11 | 0 |
| Valid JSON, wrong content | 3 (2 wrong shape, 1 bad path) | 15 (10 invented paths, 5 writes to the sandbox directory itself) |
| Failed review/tests | 2 | 1 |
| Tokens per implementation run | ~4,020 | ~1,220 (about 3.3x fewer; an earlier note said 9x, which was wrong) |
| Median whole-task wall time | ~55s | ~6s (about 9x faster) |
| Proposed test files with no `test_` function | 3/4 | 11/11 |

The constraint removed the format failure and made failure cheaper, but the content was unusable.

### C. Chat template, prompt wording and thinking (non-golden tasks)

Real `CoderAgent` (real files, real pytest), constrained decoding, four small tasks that are not in
the golden set, 12 to 28 samples per cell. Test files containing a `test_` function:

| | raw prompt text | chat template |
|---|---|---|
| original prompt (shape line with `"..."`) | 0/16 | 1/16 |
| reworded prompt (rules in words, no `"..."`) | 1/28 | 19/28 (pooled from two runs) |

- The template alone did nothing; the reworded prompt alone did nothing; both together helped. An
  earlier reading ("the template is the lever") was confounded by a simultaneous prompt change.
- Pooled comparison, raw against template with the reworded prompt: parsed 20/28 against 28/28,
  test function present 1/28 against 19/28, own tests passing 1/28 against 5/28.
- The template the server applies ends with `<think>` plus a newline; keeping or stripping it made
  no measurable difference (9 against 8 of 16).
- Letting the model think first and constraining only the final answer: 0 of 12 passing and
  slower (8.3s against 3.4s per sample).
- A worked example in the prompt was copied verbatim in 17 of 24 samples; rules only (no example,
  no `"..."`) parsed 24/24 but produced no test function. Under a grammar the server also did not
  appear to enforce a `pattern` rule on file names.

### D. Handing the goal to the Coder (rows 7 and 8)

Counting runs where the file named in the goal exists in the saved sandbox:

| | Feature runs writing the goal's file | All runs writing it |
|---|---|---|
| Before (6-run check, constrained) | 0 of 4 | not measured |
| Row 7, constrained + template + goal | 2 of 10 | 8 of 16 |
| Row 8, default + goal | 3 of 10 | 7 of 16 |

A clear but small effect on small samples. The bug-fix and clarification tasks name a file that
already exists or is easy to guess, so their numbers say little. The success count stayed at 0 of
16. In row 8, `feature_safe_divide#1` wrote a correct function into the named `mathx.py` (hidden test
3 of 3) and was still failed because the file was put in `test_files`.

### E. What inspecting failed runs showed first

In a 6-run check, the file named in the task was never written in all 4 feature runs: the Planner's
step drops it, the Coder saw only the step, and it invented `my_add.py`, `add.py`, `my_module.py`.
Every feature task's hidden test imports from the named file, so those runs could not pass.

### F. The Planner prompt (tested, rejected)

24 samples per variant on non-golden goals, real `PlannerAgent`, chat template, constrained decoding:

| Variant | Parsed | `goal` is a placeholder | Single-step plans | Steps per plan | Names the goal's file |
|---|---|---|---|---|---|
| Current prompt (shape line) | 23/24 | 2 | 9 | 2.9 | 3 |
| Same, run again | 24/24 | 2 | 9 | 3.2 | 2 |
| Format in words only | 23/24 | 0 | 0 | 5.8 | 1 |
| Words + "a small task is ONE step" | 24/24 | 0 | 1 | 4.6 | 2 |

The reworded prompt makes plans worse: the one defect it fixes (`<restate the goal>` copied into
`goal`) is harmless because nothing in `src` reads a plan's `goal`, and removing the shape line,
which shows a one-step plan, roughly doubled the steps. In the saved constrained golden run the 16
parsed plans averaged 3.4 steps (up to 7). A `maxItems` cap on `steps` in the plan schema is
honoured by llama-server (longest plan 6 to 2, mean 2.75 to 1.71, nothing unparseable, 24 samples,
feasibility only); whether it helps success is untested.

### G. Two evaluation attempts were discarded

`LlamaServerProcess` started `llama-server` with an unread `stdout=PIPE`. After roughly 14 runs of
request logging the pipe buffer filled, the server blocked on its next log write, and every
completion hung while `/health` still answered ok. Both attempts stalled at the same run, which
exposed it. Fixed in PR #24 (output goes to `LLAMA_LOG_PATH`) and verified with 300 real
completions; the published runs are later attempts. An evaluation harness is also a stress test of
the code it drives, and `/health` ok does not mean the server is serving.

### H. How far to trust these numbers

Twenty runs per row, one pass each, non-deterministic: a small sample with wide intervals, so a
difference of a few runs is noise. The prompt ablations behind rows 3 and 5 used non-golden tasks
(12 to 28 samples per cell), but the decision to drop the example and reword the prompt was also
informed by the golden-run failure classes, so the golden set is not a clean held-out test of those
changes. "Fake test" counts a run if *any* proposed test file lacks a `test_` function. The
before/after on file names compares ten runs per row against four.
