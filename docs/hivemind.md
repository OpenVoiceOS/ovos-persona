# HiveMind Integration

**Module:** `ovos_persona.hpm.PersonaProtocol`

`PersonaProtocol` exposes a `Persona` as a HiveMind agent — a satellite that handles utterances from HiveMind clients using an LLM/solver backend instead of the normal OVOS intent pipeline.

---

## Overview

`PersonaProtocol` extends `AgentProtocol` from `hivemind-core`. It is registered as a HiveMind agent plugin via the `hivemind.agent.protocol` entry point:

```
hivemind-persona-agent-plugin = ovos_persona.hpm:PersonaProtocol
```

When a HiveMind satellite connects to a hub running `PersonaProtocol`, utterances from the satellite are answered directly by the configured persona rather than being routed through the full OVOS pipeline on the hub.

---

## Usage

```python
from ovos_persona.hpm import PersonaProtocol

protocol = PersonaProtocol(
    bus=bus,
    config={
        "persona": "/path/to/my_persona.json"
    }
)
```

If `config["persona"]` is not set, a default ChatGPT-style persona is constructed pointing at a local llama endpoint.

---

## Persona Configuration

The `config["persona"]` key points to a persona JSON file (same format as user-defined personas in `PersonaService`). The file is loaded and a `Persona` instance is created from it.

If no path is provided, the default persona is:

```json
{
  "name": "ChatGPT",
  "solvers": ["ovos-solver-openai-plugin"],
  "ovos-solver-openai-plugin": {
    "api_url": "https://llama.smartgic.io/v1",
    "key": "sk-xxxx",
    "persona": "helpful, creative, clever, and very friendly."
  }
}
```

---

## Utterance Handling

`PersonaProtocol` listens for `recognizer_loop:utterance` on the internal OVOS bus. For each incoming utterance:

1. Extracts the first utterance string and the session
2. Appends a `USER` message to the session's history
3. Calls `persona.chat(history, lang=sess.lang)` for a single-shot response
4. Sends the response back to the originating HiveMind client as a `speak` message via `HiveMessage(BUS)`
5. Appends the `ASSISTANT` response to the session history

This differs from `PersonaService.handle_persona_query()`, which uses `persona.stream()` for incremental speech. `PersonaProtocol` uses `persona.chat()` for a single complete response.

---

## Session Tracking

Per-session history is maintained in `self.sessions: Dict[str, List[Dict]]` as raw `{"role": ..., "content": ...}` dicts (compatible with OpenAI-style APIs), keyed by `session_id`.
