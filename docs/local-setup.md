# Local setup

## Install

Requirements: `uv`, Git, and a LiveKit Cloud project. The project uses Python 3.12.

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

The default pipeline uses LiveKit Inference for STT, LLM, and TTS. It needs LiveKit server
credentials but no separate model-provider tokens.

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

Direct provider plugins are optional:

```bash
uv sync --extra providers
```

Set the provider's token, such as `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, or `CARTESIA_API_KEY`,
and construct the `AgentSession` at the runtime boundary. The included session factory uses
LiveKit Inference and ignores direct provider tokens.

Module 2 has a separate evaluator pipeline. Environment model descriptors configure its
LiveKit Inference defaults. Code that instantiates `LiveKitTrialRunner` may instead pass a
`pipeline_factory` returning `EvaluatorPipeline` with provider-specific STT, LLM, TTS, and VAD
objects. This is the switch point for moving either side off free LiveKit Inference credits.

## Verify

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

These checks cover software correctness; Module 2 covers real voice behavior.
