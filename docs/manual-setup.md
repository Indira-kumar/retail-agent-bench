# Manual setup

This guide starts the real Module 1 voice agent in a LiveKit room. It does not use tau's
orchestrator and does not run an evaluation.

## 1. Prerequisites

Install:

- `uv`;
- Git;
- a microphone and speaker for a manual call;
- optionally the `lk` CLI for LiveKit Cloud login and the Agent Console.

The repository is fixed to Python 3.12 through `.python-version` and `pyproject.toml`.

## 2. Install Python and dependencies

From the repository root:

```bash
uv python install 3.12
uv sync --extra dev --extra tau
```

`uv.lock` pins the complete environment. The `tau` extra installs the pinned tau Python package
and the minimal dependency needed to import its current retail runtime. It does not install or
use tau's voice stack.

## 3. Check out tau benchmark data

Tau's built wheel currently omits `data/`, so keep a checkout at the exact commit pinned by this
repository:

```bash
git clone https://github.com/sierra-research/tau2-bench.git .external/tau2-bench
git -C .external/tau2-bench checkout b7ea9074c1cba482b30687fecdb5c8425fd6f619
```

`.external/` is ignored by Git. Use an existing checkout instead if preferred.

## 4. Create LiveKit credentials

The default pipeline uses **LiveKit Inference** for STT, LLM, and TTS. Therefore it needs one
LiveKit Cloud project but no separate AssemblyAI, Google, or Fish Audio API tokens.

1. Create or select a project in the LiveKit Cloud dashboard.
2. Install the LiveKit CLI and authenticate:

   ```bash
   lk cloud auth
   ```

3. From this repository, write the selected project's server credentials:

   ```bash
   lk app env -w
   ```

This creates `.env.local` with:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
```

These are server credentials, not a participant token. Keep the API secret out of clients and
version control.

The hosted Agent Console creates its own short-lived participant token. If Module 2 or a custom
client joins a room directly, its trusted backend must mint a participant access token with room
join permission. For a temporary manual token, the LiveKit CLI supports:

```bash
lk token create --join --room retail-manual --identity manual-user
```

Never place `LIVEKIT_API_SECRET` in a browser, mobile application, evaluator artifact, or trace.

## 5. Configure Module 1

Merge the non-secret values from `.env.example` into `.env.local`, then set the tau data path:

```dotenv
LIVEKIT_AGENT_NAME=retail-support-agent
TAU2_DATA_DIR=/absolute/path/to/retail-agent-bench/.external/tau2-bench/data

RETAIL_STT_MODEL=assemblyai/universal-3-5-pro:en
RETAIL_LLM_MODEL=google/gemma-4-31b-it
RETAIL_TTS_MODEL=fishaudio/s2.1-pro:fa4c9eb3dccc4806b382b40d61c6b10a
RETAIL_VAD_MODEL=silero
RETAIL_MIN_ENDPOINTING_DELAY=0.5
RETAIL_MAX_ENDPOINTING_DELAY=3.0
RETAIL_MAX_TOOL_STEPS=8
```

`RETAIL_VAD_MODEL` only accepts `silero`. Module 1 explicitly selects VAD-only turn detection and
VAD-only interruption handling.

## 6. Start the agent

Development mode connects the worker to the configured LiveKit project:

```bash
uv run retail-voice-agent dev
```

Open the Agent Console for the project, start a session, and speak to the agent. Each room gets a
fresh tau retail environment, so manual calls do not share mutable retail state.

For the pinned LiveKit version, local console mode is also available:

```bash
uv run retail-voice-agent console
```

Console mode is useful for a quick microphone check, but Module 2 evaluations must join a real
LiveKit room as shown in the architecture diagram.

## 7. Optional direct model-provider tokens

The default setup intentionally does not need these. If you later choose LiveKit provider
plugins instead of LiveKit Inference:

```bash
uv sync --extra providers
```

Store the relevant credentials in `.env.local`:

```dotenv
OPENAI_API_KEY=...
DEEPGRAM_API_KEY=...
CARTESIA_API_KEY=...
```

Then construct an `AgentSession` with `livekit.plugins.openai`, `deepgram`, and/or `cartesia`
objects while reusing the same `RetailSupportAgent`. Provider construction belongs at the
LiveKit runtime boundary; it must not be added to the retail agent or Tau adapter. The included
`create_livekit_session` uses LiveKit Inference descriptors and intentionally ignores direct
provider tokens.

## 8. Supply a different runtime

The default server loads
`retail_agent.integrations.tau:load_default_retail_bindings`. To inject another DB, policy, and
tool instance, expose a zero-argument function returning `RuntimeBindings`:

```python
from retail_agent import RuntimeBindings


def build_bindings() -> RuntimeBindings:
    db = make_isolated_db()
    toolkit = make_retail_tools(db)
    return RuntimeBindings(policy=load_policy(), tools=toolkit, db=db)
```

Point the worker at it:

```dotenv
RETAIL_BINDINGS_FACTORY=my_runtime:build_bindings
```

The factory runs once per LiveKit room. Do not return a singleton DB when running evaluations.

## 9. Verify code quality

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

These are software checks only. Agent behavior is evaluated with real voice sessions in Module 2.
