# Module 1 architecture

## Ownership

Module 1 adheres to the boundaries in the repository diagram.

| Component | Owner | Responsibility |
| --- | --- | --- |
| Evaluator, scenarios, trace persistence | Module 2 | Join rooms, drive real audio, store and score trajectories |
| LiveKit room | LiveKit / Module 2 | Transport participant and agent audio and room events |
| `AgentSession` | Module 1 via LiveKit | VAD, STT, LLM, TTS, interruption handling, tool loop |
| `RetailSupportAgent` | Module 1 | Injected policy, voice instructions, tool surface, run metadata |
| `TauToolAdapter` | Module 1 | Schema conversion, invocation, serialization, errors, tool events |
| Retail policy, tools, and DB | Tau runtime | Domain behavior and mutable evaluation state |

There is no dependency from Module 1 to Module 2. Module 2 imports Module 1 and provides an
optional event sink.

## Runtime construction

For each room or evaluation run:

1. The runtime creates an isolated `RetailDB` and `RetailTools` instance.
2. The runtime passes the policy and DB-bound tools into `create_retail_agent`.
3. `TauToolAdapter` validates and converts tau's OpenAI-style schemas to LiveKit raw tools.
4. `create_livekit_session` configures the STT-LLM-TTS pipeline and pure Silero VAD turn
   handling.
5. LiveKit starts the session in the room.

The `RuntimeBindings.db` field exists for the runtime/evaluator to retain the DB and calculate
tau outcomes. `RetailSupportAgent` does not receive or inspect it.

## Tool adapter contract

The adapter accepts any of the following:

- a tau `ToolKitBase`-compatible object with `get_tools()`;
- a mapping of tool name to tau `Tool`;
- a list or tuple of tau `Tool` objects.

Each tool must expose `name`, `openai_schema`, and `__call__(**kwargs)`. The adapter:

- preserves tool and parameter names exactly;
- uses the descriptions and JSON Schema supplied by tau;
- executes tau's in-memory synchronous tools inside a serialized LiveKit tool step;
- serializes Pydantic and standard Python return values predictably;
- serializes calls with an async lock so the in-memory DB cannot be mutated concurrently;
- re-raises domain errors so LiveKit returns the failed tool outcome to the LLM;
- observes tau tool category/mutation metadata when a toolkit object is supplied;
- does not decide whether a tool call complies with policy.

## Prompt-based compliance

The injected tau policy is inserted verbatim inside a clearly delimited policy section. Stable
voice rules add concise speech, one question at a time, explicit confirmation for writes, and
one in-flight tool call. No deterministic authentication or confirmation guard exists in Module
1. This is intentional: failure trajectories from Module 2 will determine whether a targeted
guard belongs in Module 3.

## Turn handling

`create_livekit_session` sets both:

- `turn_detection="vad"`;
- interruption mode to `"vad"`.

It uses Silero VAD and does not instantiate LiveKit's semantic/audio turn detector. Preemptive
generation is disabled by default so evaluation traces correspond to completed voice turns.

## Structured events

`create_retail_agent(..., event_sink=...)` accepts a synchronous or asynchronous sink. Delivery
runs in background tasks and never delays the agent or a tool call. A synchronous sink must do
constant-time work such as `list.append` or `queue.put_nowait`; persistence belongs in its own
consumer. Events include:

- agent and session creation metadata;
- LiveKit transcript, conversation, speech, state, usage, error, and close events;
- tool start, completion, duration, arguments, result, and failure events.

Every event contains an event ID, session ID, UTC timestamp, monotonic timestamp, source, kind,
and JSON-safe payload. Module 1 does not write these events to disk. Module 2 is responsible for
retention and for associating room audio with the structured trajectory.

Call `await agent.event_emitter.drain()` during controlled shutdown when the trace collector must
flush every scheduled event.

## Dependency boundary

The core package structurally types tau tools and imports tau only inside the optional default
bindings loader. This keeps `import retail_agent` clean when a caller supplies another
tau-compatible runtime. Versions are pinned in `pyproject.toml` and `uv.lock` for reproducible
evaluation runs.
