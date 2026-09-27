# Local setup

## Install

Requirements: `uv`, Git, a LiveKit Cloud project, and a Deepgram API key. The project uses
Python 3.12.

```bash
uv python install 3.12
uv sync --extra dev --extra tau
```

`uv.lock` pins the environment. The `tau` extra installs tau's retail runtime, not its voice
stack or orchestrator.

## Add tau benchmark data

Tau's wheel omits `data/`, so check out the pinned commit:

```bash
git clone https://github.com/sierra-research/tau2-bench.git .external/tau2-bench
git -C .external/tau2-bench checkout b7ea9074c1cba482b30687fecdb5c8425fd6f619
```

## Configure LiveKit

The default pipeline uses direct Deepgram for STT and TTS and LiveKit Inference for the LLM. It
needs LiveKit server credentials and a Deepgram API key.

Install live kit using [live kit setup docs](https://docs.livekit.io/reference/developer-tools/livekit-cli/#setup)

```bash
lk cloud auth
lk app env -w
```

This writes `.env.local`. Add the non-secret settings from `.env.example` and set:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
DEEPGRAM_API_KEY=...
TAU2_DATA_DIR=/absolute/path/to/retail-agent-bench/.external/tau2-bench/data
```

Replace `/absolute/path/to/retail-agent-bench` with the repository's actual absolute path. Do
not leave the example value unchanged. Confirm the configured checkout contains the retail data:

Keep `LIVEKIT_API_SECRET` out of clients, traces, and version control. A trusted backend must
mint participant tokens for room clients. For a temporary manual token:

```bash
lk token create --join --room retail-manual --identity manual-user
```

## Run

```bash
uv run retail-voice-agent dev
```

Join through the LiveKit Agent Console and speak to the agent. Local microphone-only checking is
also available with `uv run retail-voice-agent console`; evaluation must use a real LiveKit room.
Every room receives fresh tau runtime bindings.

## Run Module 2

Keep the named retail worker running, then use a second terminal:

```bash
uv run retail-eval list-tasks --split test
uv run retail-eval run \
  --selection-file eval-selection.json \
  --trials 1 \
  --concurrency 3
```

The selection file is either a JSON list or an object:

```json
{
  "task_ids": ["task-id-1", "task-id-2", "task-id-3"]
}
```

Select 20–30 tasks for a full benchmark. Start with one task and `--concurrency 1` to validate
credentials and agent dispatch. Module 2 accepts at most five concurrent rooms. Results are
written under `eval-runs/<experiment-id>/` by default.

## Visualize trajectories

Point the visualizer at a completed experiment directory. The directory must contain
`experiment.json` and `summary.json` at its root:

```bash
uv run retail-eval visualize eval-runs/<experiment-id>
```

For the checked-in example run:

```bash
uv run retail-eval visualize evals-results/retail-8-tasks-c3
```

The command starts a local server at `http://127.0.0.1:8765` and opens the visualizer in a
browser. Select a task in the left rail, then select a trial in the task header. The available
views are:

- **Trajectory** — the timestamped STT transcript, LLM/TTS responses, tool calls, tool results,
  and tool failures from `events.jsonl`. Switch to **All logs** to include the complete LiveKit
  event stream.
- **Evaluation** — expected action checks, failure labels, and the reward breakdown from
  `score.json` and `failure.json`.
- **Relevant policy** — the policy sections selected for the task from `relevant_policy.json`.

The customer and agent audio players read `input.wav` and `output.wav` from the selected trial.
Task and trajectory search filters are applied locally and do not modify the artifacts.

Use a different port or prevent the browser from opening automatically when needed:

```bash
uv run retail-eval visualize eval-runs/<experiment-id> --port 9000 --no-open
```

Stop the local server with `Ctrl-C`.

## Optional configuration

Model and VAD settings live in `.env.example`. `RETAIL_VAD_MODEL` must remain `silero`; Module 1
uses VAD-only turn detection and interruption handling.

To replace the default tau loader, expose a zero-argument factory returning `RuntimeBindings`:

```python
from retail_agent import RuntimeBindings


def build_bindings() -> RuntimeBindings:
    db = make_isolated_db()
    tools = make_retail_tools(db)
    return RuntimeBindings(policy=load_policy(), tools=tools, db=db)
```

```dotenv
RETAIL_BINDINGS_FACTORY=my_runtime:build_bindings
```

The factory runs once per room. Do not reuse a mutable DB between evaluations.

Optional LLM provider plugins are installed with:

```bash
uv sync --extra tau --extra providers --extra dev
```

To use OpenRouter for the LLM while keeping STT and TTS on direct Deepgram, set these values in
`.env.local` after installing the providers extra:

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
RETAIL_LLM_PROVIDER=openrouter
RETAIL_LLM_MODEL=openrouter/auto
EVAL_LLM_PROVIDER=openrouter
EVAL_LLM_MODEL=openrouter/auto
```

`RETAIL_STT_MODEL`, `RETAIL_STT_LANGUAGE`, and `RETAIL_TTS_MODEL` select the direct Deepgram
models used by the retail agent. Their `EVAL_` equivalents independently select models for the
evaluator caller, while both paths use the same provider implementation and API key. The
OpenRouter switch is lazy, so the default `livekit` LLM configuration does not import the
optional OpenAI plugin.

Code that instantiates `LiveKitTrialRunner` may still pass a `pipeline_factory` returning an
`EvaluatorPipeline` for specialized tests.

## Verify

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

These checks cover software correctness; Module 2 covers real voice behavior.
