# Module 1 implementation notes

This file records constraints and decisions that future coding sessions must preserve.

## Boundaries

| Owner | Responsibility |
| --- | --- |
| Module 1 | LiveKit session composition, retail agent, tau tool adapter, structured events |
| Module 2 | Real-voice scenarios, room participation, trace persistence, tau tasks and scoring |
| LiveKit | Room transport plus VAD, STT, LLM, TTS, interruptions, and the tool loop |
| Tau runtime | Retail policy, tool implementations, and mutable database |

Module 1 must remain independently importable and must not depend on Module 2. Do not use tau's
orchestrator. Do not add a semantic turn detector or deterministic policy middleware without
evaluation evidence and an explicit design change.

## Construction flow

For each LiveKit room:

1. The bindings factory creates an isolated DB and DB-bound tau toolkit.
2. `create_retail_agent` receives the policy and tools, then adapts the tools and composes the
   policy prompt.
3. `create_livekit_session` configures LiveKit Inference and pure Silero VAD handling.
4. LiveKit starts the agent in the room and owns the voice/tool execution loop.
5. Module 2 consumes structured events and replays completed tool calls through tau's evaluator
   to derive the final DB state.

`RuntimeBindings.db` is available to an in-process integrator. Module 2 does not share that
object across LiveKit workers: tau scoring reconstructs final state from the captured tool
trajectory. `RuntimeBindings.owner` keeps the source environment alive. The agent never receives
or reads the DB directly.

## Tool adapter

`TauToolAdapter` accepts a toolkit with `get_tools()`, a name-to-tool mapping, or a list/tuple of
tools. Each tool must provide `name`, `openai_schema`, and `__call__(**kwargs)`.

The adapter preserves tau names and JSON schemas, serializes standard and Pydantic results,
re-raises domain failures for LiveKit, and emits call/result/error events. An async lock
serializes synchronous in-memory tool calls so concurrent calls cannot mutate the DB. Toolkit
metadata is observed when available. Policy compliance does not belong in the adapter.

## Prompt and turn decisions

The tau policy is injected verbatim inside a delimited prompt section. Stable voice instructions
require concise speech, one focused question, explicit confirmation before mutations, and one
tool call at a time. Compliance is prompt-based for Module 1; failed voice evaluations will
determine whether Module 3 needs targeted guards.

`create_livekit_session` sets `turn_detection="vad"`, VAD interruption mode, Silero VAD, and
preemptive generation off by default. This intentionally excludes LiveKit's semantic/audio turn
detector and keeps traces aligned with completed voice turns.

## Event contract

`create_retail_agent(..., event_sink=...)` accepts a sync or async sink. Delivery is scheduled in
background tasks and must not delay voice or tool execution. Sync sinks must do constant-time
work; persistence belongs in Module 2.

Events cover agent/session creation, LiveKit transcript and state events, usage/errors/close, and
tool start/completion/failure with arguments, results, and duration. Each event has an ID,
session ID, UTC and monotonic timestamps, source, kind, and JSON-safe payload. Module 1 never
writes traces or audio to disk. Use `await agent.event_emitter.drain()` during controlled
shutdown when all scheduled events must be flushed.

## Dependency decisions

- Python is fixed at 3.12; dependencies are locked with `uv`.
- Tau is pinned to commit `b7ea9074c1cba482b30687fecdb5c8425fd6f619`.
- Tau imports remain inside the optional default loader so `import retail_agent` works with an
  injected compatible runtime.
- Tau's wheel omits benchmark data. `TAU2_DATA_DIR` must point to the pinned checkout's `data/`.
- LiveKit Inference is the default model route. Direct provider construction stays at the
  `AgentSession` boundary.
- Unit and integration checks validate code contracts; behavioral evaluation uses real voice in
  Module 2 rather than test-based dialogue simulations.
