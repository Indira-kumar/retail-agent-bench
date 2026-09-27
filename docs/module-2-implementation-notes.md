# Module 2 implementation notes

## Boundary

| Owner | Responsibility |
| --- | --- |
| Module 2 | Task selection, evaluator caller, room orchestration, artifacts, tau scoring, failure clustering |
| Module 1 | Retail policy prompt, tool execution, and structured session/tool events |
| LiveKit | Realtime room transport and optional secondary audio/session inspection |
| Tau | Retail tasks, policy, tool contracts, and authoritative trajectory evaluation |

Module 2 does not use a LiveKit evaluation webhook or cloud callback to decide a score. The
score is calculated locally from the captured trajectory with tau's evaluator. LiveKit's
recording and Insights remain useful as a secondary way to inspect audio.

## Trial lifecycle

Each task/trial pair gets a unique room and a fresh Module 1 worker:

1. Module 2 joins as a voice customer using tau's voice-user guidelines and task scenario.
2. It explicitly dispatches the named retail agent after the evaluator session is ready.
3. The two agents converse through real room audio. Separate WAV taps retain caller input and
   retail-agent output.
4. Module 1 sends transcript, tool, error, and usage events over a versioned reliable room-data
   topic. Messages are compressed and chunked.
5. At completion or timeout, Module 2 sends a stop control message. Module 1 drains pending
   events and sends a final session report before shutting down.
6. Module 2 normalizes agent-side transcripts and exact tool results into a tau trajectory.
7. Tau replays the trajectory to evaluate final DB state, expected actions, communication, and
   any natural-language assertions declared by the task.

Scoring depends on the durable trajectory, not the optional final LiveKit session report. If
the report is late or absent, the trial can still be evaluated.

## Parallel rooms

`BenchmarkRunner` applies a semaphore around complete room lifecycles. The default concurrency
is three and the accepted range is one through five. A failure in trial setup or tau scoring is
recorded for that trial and does not cancel the remaining rooms.

Room names include the task ID, trial number, and a random suffix. This prevents mutable tau DB
instances, audio, and event streams from crossing trial boundaries.

## Artifact layout

```text
eval-runs/<experiment-id>/
├── experiment.json
├── summary.json
├── failure_clusters.json
└── task_<task-id>/trial_<n>/
    ├── task.json
    ├── policy.md
    ├── relevant_policy.json
    ├── input.wav
    ├── output.wav
    ├── events.jsonl
    ├── evaluator_events.json
    ├── evaluator_history.json
    ├── session_report.json
    ├── simulation.json
    ├── score.json
    └── failure.json
```

`input.wav` is the synthesized customer audio sent to the room. `output.wav` is the retail
agent audio received by the evaluator. An audio file is absent when that side produced no
frames. `events.jsonl` is the primary ordered trace source; `simulation.json` is its normalized
tau representation.

`relevant_policy.json` is a deterministic convenience view based on the task's expected tools.
`policy.md` remains the complete authoritative policy.

## Failure clustering

The initial clustering groups failed trials by deterministic labels:

- DB final-state mismatch
- failed natural-language, communication, or expected-action checks
- tool, transcription, or session errors
- timeout or infrastructure failure
- scoring failure

This deliberately avoids an LLM clustering pass. After enough trajectories exist, Module 3 can
use these coarse clusters plus manual audio review to identify three repeatable behaviors and
turn them into focused custom evals.

## Provider replacement

Retail-agent providers remain configured through `VoicePipelineConfig`. The evaluator caller
has independent `EVAL_STT_MODEL`, `EVAL_STT_LANGUAGE`, `EVAL_LLM_MODEL`, and `EVAL_TTS_MODEL`
settings. Both paths construct speech clients with the same `DeepgramSpeechProvider` and
`DEEPGRAM_API_KEY`. Set `EVAL_LLM_PROVIDER=openrouter` to use OpenRouter for evaluator LLM calls;
evaluator speech remains on direct Deepgram.

`LiveKitTrialRunner(..., pipeline_factory=...)` accepts a factory returning
`EvaluatorPipeline`. The factory seam remains available for specialized test pipelines;
benchmark orchestration, artifacts, and tau scoring do not change.
