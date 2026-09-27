# Local setup

Run these steps from the repository root. You need `uv`, `git`, a LiveKit Cloud project, and a
Deepgram API key.

## 1. Install the project

```bash
uv python install 3.12
uv sync --extra dev --extra tau
```

## 2. Download tau data

```bash
git clone https://github.com/sierra-research/tau2-bench.git .external/tau2-bench
git -C .external/tau2-bench checkout b7ea9074c1cba482b30687fecdb5c8425fd6f619
```

## 3. Set up LiveKit

Install the LiveKit CLI:

```bash
brew install livekit-cli                    # macOS
curl -sSL https://get.livekit.io/cli | bash # Linux
```

Authenticate and write your LiveKit credentials to `.env.local`:

```bash
lk cloud auth
lk app env -w
```

## 4. Configure Deepgram and tau

Add these values to `.env.local`:

```dotenv
DEEPGRAM_API_KEY=your-deepgram-key
TAU2_DATA_DIR=/absolute/path/to/retail-agent-bench/.external/tau2-bench/data
```

## 5. Optional: use OpenRouter

Install the provider and add these values to `.env.local`:

```bash
uv sync --extra dev --extra tau --extra providers
```

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
RETAIL_LLM_PROVIDER=openrouter
RETAIL_LLM_MODEL=openrouter/auto
EVAL_LLM_PROVIDER=openrouter
EVAL_LLM_MODEL=openrouter/auto
```

## 6. Run the app

Development mode:

```bash
uv run retail-voice-agent dev
```

Console mode:

```bash
uv run retail-voice-agent console
```

## 7. Run an evaluation

List available tasks, then run the task IDs you want:

```bash
uv run retail-eval list-tasks --split test
uv run retail-eval run --task-ids 5,9,12 --concurrency 3
```

## 8. Visualize an evaluation

Replace `<experiment-id>` with the directory created by the evaluation:

```bash
uv run retail-eval visualize eval-runs/<experiment-id>
```
