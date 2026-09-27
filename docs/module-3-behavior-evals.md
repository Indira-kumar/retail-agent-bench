# Module 3: prompt-behavior evals

This suite converts repeated failures from the three baseline voice runs into three deterministic
behavior evals. It reads the same `task.json` and `simulation.json` artifacts produced by Module 2;
it does not call an LLM grader. That makes a pre/post prompt comparison independent of grader
availability and scoring variance.

## Selected behaviors

### 1. Canonicalize spoken email addresses

Task 40 supplied `isabella.lopez3271@example.com` as spoken words. The agent called
`find_user_id_by_email` with `Isabella.Lopez.3271@example.com`, introducing an extra separator and
then abandoning email authentication after the lookup failed.

The eval passes when the trajectory contains the exact expected email lookup declared by tau. The
prompt target is to translate spoken punctuation and digits, normalize email casing, read the
result back when uncertain, and never invent separators.

### 2. Recover exact names for authentication

Tasks 49, 51, and 53 fail on spoken names. The trajectories include `Adar Vonderson`,
`Ara Vase Anderson`, `Arav Anderson`, and `Sophia Lee Paz`; some incorrect arguments are retried
unchanged before transfer. These runs happened after the main harness fixes and reproduce across
two task sets.

The eval passes when each trajectory eventually contains the exact expected
`find_user_id_by_name_zip` action declared by tau. A prompt can improve this by asking the customer
to spell first and last names separately after a failed lookup, reconstructing the two fields, and
reading them back before retrying.

### 3. Explain tool rejections truthfully

In task 27, the return succeeds first and changes the order to `return requested`. The subsequent
exchange tool returns `Non-delivered order cannot be exchanged`. The agent calls this an internal
error and transfers the customer, even though the tool supplied the real business-state reason.

The eval passes when the customer-facing response mentions both the exchange and either the
delivery or return state, and does not claim an internal error. This tests communication grounding;
it does not require a particular recovery or escalation choice.

## Why other failures are excluded

- Tasks 5, 12, 32, 55, and 101 are dominated by wall-clock timeout or user-simulator behavior.
- Tasks 45, 62, and 68 contain scoring or session errors despite plausible trajectories.
- Literal `pause` utterances and silence after transfer are harness concerns, not prompt behavior.
- Tasks 9 and 18 support the name hypothesis, but predate the main harness fixes. The suite uses
  the cleaner failures from tasks 49, 51, and 53 instead.

Those cases remain useful for harness regression tests, but mixing them into this suite would make
the prompt experiment difficult to interpret.

## Run the experiment

Capture a fresh baseline or post-prompt run with the versioned task selection:

```bash
uv run retail-eval run \
  --selection-file evals/retail-prompt-behaviors.json \
  --trials 3 \
  --concurrency 3 \
  --experiment-id retail-prompt-behaviors-prompt-v2
```

Then score the resulting experiment directory:

```bash
uv run retail-behavior-eval eval-runs/retail-prompt-behaviors-prompt-v2
```

The command prints JSON and exits with status 1 while any behavior fails. Use `--output` to retain
a comparison report outside the experiment artifacts:

```bash
uv run retail-behavior-eval \
  eval-runs/retail-prompt-behaviors-prompt-v2 \
  --output behavior-report.json
```

Use a unique experiment ID for each prompt version. Keep the model, temperature, voice, STT, TTS,
timeout, trial count, and concurrency fixed between versions. The suite requires every supplied
trial to pass, so the report exposes regressions instead of averaging them away.

## Baseline artifact check

The current evidence spans the curated first two runs and the ignored third run:

```bash
uv run retail-behavior-eval \
  evals-results/run-1-retail-8-tasks-c3 \
  evals-results/run-2-retail-6-diverse-c3 \
  eval-runs/retail-6-diverse-c3-run3
```

This command is expected to fail all three behaviors before prompt optimization. The third run is
currently under `eval-runs/`; copy it to `evals-results/` only if you decide it is suitable for the
curated repository evidence.
