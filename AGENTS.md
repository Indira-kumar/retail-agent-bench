This repository consists of three main components (all of them yet to be built)

Module 1:
- contains retail support voice assistant
- the VAD, STT, TTS, LLM model providers are taken care of by live kit (docs at https://docs.livekit.io/agents/)
- the core harness should be focused on the business logic.
- create adaptors for tools (will be provided by tau https://github.com/LLM360/tau2-bench/blob/main/src/tau2/domains/retail/tools.py)
- the agent must be a clean importable, evaluatble module. the DB, policy, and tools will be provided/instantiated at runtime.
- you can assume the shape of DB, tools, policy to be similar to https://github.com/LLM360/tau2-bench/tree/main/src/tau2/domains/retail

Module 2:
- contains EVAL environment
- Runs 20-30 choosen evals from https://github.com/LLM360/tau2-bench/tree/main/data/tau2/domains/retail
- Documents traces. Each trace contain input voice, STT, LLM output, tool calls, tools result, TTS
- For a given task, I want to be able to check audio trajectories, relevant policy and the tool calls 

Module 3:
- This will be my custom EVALS after analysing runs from module 2. 
- Will be focusing on failed behaviours and improvise harness for the same


Coding guidelines:
- format, sort imports, lint before any commit
- use design principles when mentioned and when there is scope for simplification
- use clean, concise descriptive names for functions (use snake case)
- no function description comments, the function name tells what it does