# Persona

**Module:** `ovos_persona.Persona`

`Persona` is the runtime representation of a single named AI personality. It holds the ordered solver pipeline for answering queries and optionally a memory plugin for maintaining conversation history.

---

## Constructor

```python
from ovos_persona import Persona

persona = Persona(name="MyChatBot", config={...}, blacklist=[])
```

| Parameter | Description |
|---|---|
| `name` | Display name of the persona |
| `config` | Persona config dict (from JSON file or plugin) |
| `blacklist` | List of solver plugin names to never load for this persona |

Raises `ValueError` if the config provides no handler plugins.

---

## Configuration Keys

| Key | Description |
|---|---|
| `handlers` | Ordered list of utterance handler plugin entry point names (preferred key) |
| `solvers` | Same as `handlers` (legacy alias) |
| `memory_module` | Entry point name of the memory plugin (default: `ovos-agents-short-term-memory-plugin`) |
| `<plugin_name>` | Per-plugin configuration dict passed to each handler |

```json
{
  "name": "MyChatBot",
  "handlers": [
    "ovos-solver-openai-plugin",
    "ovos-solver-wolfram-alpha-plugin"
  ],
  "ovos-solver-openai-plugin": {
    "api_url": "https://api.openai.com/v1",
    "key": "sk-..."
  },
  "memory_module": "ovos-agents-short-term-memory-plugin"
}
```

---

## Memory

If `memory_module` is set (and not empty), the plugin is loaded via `load_memory_plugin()`. The default is `BasicShortTermMemory` from this package.

Set `memory_module` to `null` or `""` to disable memory entirely:

```json
{
  "name": "Stateless",
  "handlers": ["ovos-solver-openai-plugin"],
  "memory_module": null
}
```

Without memory, each utterance is sent to the solver as a single `USER` message with no history context.

---

## Key Methods

### `get_messages(utterance, sess) → List[AgentMessage]`

Build the message list to send to the solver:
- **With memory**: calls `memory.build_conversation_context(utterance, sess.session_id)` — prepends system prompt and prior history
- **Without memory**: returns `[AgentMessage(MessageRole.USER, utterance)]`

### `chat(messages, sess) → str`

Single-shot completion. Returns the full response as a string. Used by `PersonaProtocol` (HiveMind integration).

### `stream(messages, sess) → Iterable[str]`

Streaming completion. Yields response sentences as they are produced. Used by `PersonaService.handle_persona_query()` to speak answers incrementally.

Both methods delegate to `QuestionSolversService`, passing `sess.lang` and `sess.system_unit`.

---

## Repr

```python
repr(persona)
# → "Persona(MyChatBot:['ovos-solver-openai-plugin', 'ovos-solver-wolfram-alpha-plugin'])"
```
