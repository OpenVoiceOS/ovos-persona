# Memory

**Module:** `ovos_persona.memory.BasicShortTermMemory`

`BasicShortTermMemory` is the default memory implementation for personas. It maintains per-session conversation history in RAM and provides it as context when querying a solver.

---

## Overview

```python
from ovos_persona.memory import BasicShortTermMemory

memory = BasicShortTermMemory(config={"max_history": 10, "system_prompt": "You are helpful."})
```

Registered as entry point `ovos-agents-short-term-memory-plugin` in the `opm.agents.memory` group. Loaded by `Persona.__init__` via `load_memory_plugin()`.

To use a different memory backend, set `memory_module` in the persona config to any installed `opm.agents.memory` plugin entry point.

---

## Configuration

| Key | Default | Description |
|---|---|---|
| `max_history` | `5` | Maximum number of messages to retain per session |
| `system_prompt` | `""` | System prompt prepended to every context |

---

## Session History

History is stored as `{session_id: List[AgentMessage]}`.

Each `AgentMessage` has a `role` (`USER`, `ASSISTANT`, or `SYSTEM`) and `content` (string).

### `update_history(new_messages, session_id)`

Appends messages to the session history with two normalisation rules:

- **Hanging user messages**: if the last stored message is `USER` and the next message is also `USER`, the last one is dropped (e.g. an utterance that produced no response).
- **Consecutive assistant messages**: if both the last stored and the next message are `ASSISTANT`, they are merged into a single message with a newline separator (e.g. multiple `speak` events from one response).

After appending, history is truncated to the most recent `max_history` messages.

### `get_history(session_id) → List[AgentMessage]`

Returns a copy of the session's message list. Returns `[]` for unknown sessions.

---

## `build_conversation_context(utterance, session_id) → List[AgentMessage]`

Produces the full message list to pass to a solver:

1. Retrieve history for the session
2. Drop any trailing `USER` messages without a matching `ASSISTANT` response
3. If `system_prompt` is non-empty, prepend `AgentMessage(SYSTEM, system_prompt)` at position 0
4. Append `AgentMessage(USER, utterance)` at the end

```python
context = memory.build_conversation_context("what is the capital of France?", "sess-123")
# → [
#     AgentMessage(SYSTEM, "You are a helpful assistant."),
#     AgentMessage(USER,   "what is 2+2?"),
#     AgentMessage(ASSISTANT, "4"),
#     AgentMessage(USER,   "what is the capital of France?")
# ]
```

---

## Memory Plugin Interface

`BasicShortTermMemory` extends `AgentContextManager` from `ovos-plugin-manager`. Third-party memory plugins (e.g. persistent database-backed, vector-store-based) implement the same interface:

| Method | Description |
|---|---|
| `get_history(session_id)` | Return message history for a session |
| `update_history(new_messages, session_id)` | Append new messages to session history |
| `build_conversation_context(utterance, session_id)` | Produce the full message list for a solver query |

Install a third-party plugin and set `memory_module` in the persona config to its entry point name to use it.
