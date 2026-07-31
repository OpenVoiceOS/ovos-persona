# QuestionSolversService

**Module:** `ovos_persona.solvers.QuestionSolversService`

Manages the ordered pipeline of utterance handler plugins for a `Persona`. Tries each handler in order and returns the first successful response.

---

## Supported Plugin Types

`QuestionSolversService` supports six plugin categories, all discovered via `ovos-plugin-manager`:

| Entry point group | Base class | Chat history support | Streaming |
|---|---|---|---|
| `opm.solver` | `QuestionSolver` | No, last message only | Yes (`stream_utterances`) |
| `opm.solver.chat` | `ChatMessageSolver` | Yes | Yes (`stream_chat_utterances`) |
| `opm.agents.chat` | `ChatEngine` | Yes | Yes (`stream_sentences`) |
| `opm.agents.chat.multimodal` | `MultimodalChatEngine` | Yes | Yes (`stream_sentences`) |
| `opm.agents.retrieval` | `RetrievalEngine` | No, last message only | No |
| `opm.agents.indexer.document` | `DocumentIndexerEngine` | No, last message only | No |
| `opm.agents.indexer.qa` | `QAIndexerEngine` | No, last message only | No |

`QuestionSolversService` treats all plugin types the same way. It dispatches to the method that matches the plugin's class.

---

## Plugin Ordering

The `sort_order` parameter (set from the persona's `handlers` list) controls the order in which plugins are tried:

```python
service = QuestionSolversService(
    config={"ovos-solver-openai-plugin": {"enabled": True}},
    sort_order=["ovos-solver-wolfram-alpha-plugin", "ovos-solver-openai-plugin"]
)
```

If `sort_order` is empty, plugins are sorted by their `priority` attribute (lower = tried first).

`stream_completion` stops after the first handler that yields at least one sentence. It does not try the remaining handlers.

---

## `get_utterance_handler_plugins()`

```python
from ovos_persona.solvers import get_utterance_handler_plugins

plugins = get_utterance_handler_plugins()
# → {entry_point_name: PluginClass, ...}
```

Merges all six plugin entry point groups into a single dict. Used by `Persona.__init__` to build the handler config.

---

## `chat_completion(messages, lang, units) → Optional[str]`

Single-shot: tries each handler in order and returns the first non-empty string response.

Dispatch logic:

| Plugin type | Method called |
|---|---|
| `ChatEngine` / `MultimodalChatEngine` | `continue_chat(messages, ...)` → `response.content` |
| `RetrievalEngine` / `DocumentIndexerEngine` / `QAIndexerEngine` | `query(last_message, k=1)` → first document |
| `ChatMessageSolver` | `get_chat_completion(messages, ...)` |
| `QuestionSolver` | `spoken_answer(last_message, ...)` (no history) |

---

## `stream_completion(messages, lang, units) → Iterable[str]`

Streaming: yields response sentences from the first handler that produces output. Stops trying further handlers once any handler yields at least one sentence.

Dispatch logic:

| Plugin type | Method called |
|---|---|
| `ChatEngine` / `MultimodalChatEngine` | `stream_sentences(messages, ...)` |
| `RetrievalEngine` / `DocumentIndexerEngine` / `QAIndexerEngine` | `query(last_message, k=1)` → yields document |
| `ChatMessageSolver` | `stream_chat_utterances(messages, ...)` |
| `QuestionSolver` | `stream_utterances(last_message, ...)` (no history) |

---

## Configuration

Each handler plugin is configured by its entry point name inside the persona config:

```json
{
  "handlers": ["ovos-solver-openai-plugin", "ovos-solver-wolfram-alpha-plugin"],
  "ovos-solver-openai-plugin": {
    "enabled": true,
    "api_url": "https://api.openai.com/v1",
    "key": "sk-..."
  },
  "ovos-solver-wolfram-alpha-plugin": {
    "enabled": true,
    "key": "..."
  }
}
```

Handlers not in the persona's `handlers` list are disabled regardless of their `enabled` key. If a handler listed in `handlers` is not installed, `ImportError` is raised during `load_plugins()`.

---
[← Persona](persona.md) · [Home](index.md) · [Memory →](memory.md)
