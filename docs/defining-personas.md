# Defining Personas

Personas can be defined in two ways: as JSON files placed in the persona config directory, or as Python packages that register an `opm.persona` entry point.

---

## User-Defined JSON Files

Place a `.json` file in the persona config directory (default: `~/.config/ovos_persona/`):

```
~/.config/ovos_persona/
├── mychatbot.json
└── researcher.json
```

The filename (without `.json`) is used as the persona name unless the JSON provides a `"name"` field.

### Minimal Example

```json
{
  "name": "MyChatBot",
  "handlers": ["ovos-chat-openai-plugin"],
  "ovos-chat-openai-plugin": {
    "api_url": "https://api.openai.com/v1",
    "key": "sk-..."
  }
}
```

### Full Example with Memory and Fallback

```json
{
  "name": "Researcher",
  "handlers": [
    "ovos-chat-openai-plugin",
    "ovos-wolfram-alpha-plugin",
    "ovos-wikipedia-plugin"
  ],
  "memory_module": "ovos-agents-short-term-memory-plugin",
  "ovos-agents-short-term-memory-plugin": {
    "max_history": 10,
    "system_prompt": "You are a helpful research assistant. Answer factually and cite sources."
  },
  "ovos-chat-openai-plugin": {
    "api_url": "https://api.openai.com/v1",
    "key": "sk-...",
    "model": "gpt-4"
  },
  "ovos-wolfram-alpha-plugin": {
    "key": "..."
  }
}
```

---

## Schema Reference

| Key | Type | Required | Description |
|---|---|---|---|
| `name` | `str` | No | Display name (overrides filename) |
| `handlers` | `List[str]` | **Yes** | Ordered list of utterance handler plugin entry point names |
| `solvers` | `List[str]` | No | Alias for `handlers` (legacy) |
| `memory_module` | `str` | No | Memory plugin entry point name. Default: `ovos-agents-short-term-memory-plugin`. Set to `null` to disable. |
| `<plugin_name>` | `dict` | No | Per-plugin config dict, passed directly to the plugin constructor |

At least one entry in `handlers` / `solvers` is required. If a listed handler is not installed, loading the persona will fail with `ImportError`.

---

## Utterance Handler Types

The `handlers` list may include plugins from any of these entry point groups:

| Entry point group | Example plugin | Description |
|---|---|---|
| `opm.solver.question` | `ovos-solver-rivescript-plugin` | Q&A, answers single questions, no chat history |
| `opm.solver.chat` | none | Chat solver with history support |
| `opm.agents.chat` | `ovos-chat-openai-plugin` | Full LLM chat engine |
| `opm.agents.chat.multimodal` | none | Multimodal LLM engine |
| `opm.agents.retrieval` | `ovos-wolfram-alpha-plugin`, `ovos-wikipedia-plugin` | RAG retrieval engine, answers directly with no LLM in front of it |
| `opm.agents.retrieval.documents` | none | Document indexer for RAG |
| `opm.agents.retrieval.qa` | none | QA indexer for RAG |

Plugins are tried in the order listed in `handlers`. The first handler that returns a non-empty response wins.

---

## Plugin Personas (Entry Points)

Python packages can ship pre-defined personas via the `opm.persona` entry point group:

```toml
# pyproject.toml
[project.entry-points."opm.persona"]
my-persona-plugin = "my_package:my_persona_config"
```

Where `my_persona_config` is a `dict` with the same structure as the JSON format above.

Plugin personas are loaded after user JSON files. If a user file with the same name exists, the plugin persona is silently ignored. All plugin personas can be disabled with `ignore_plugin_personas: true` in config.

---

## Disabling Memory

To create a stateless persona (no conversation history):

```json
{
  "name": "Stateless",
  "handlers": ["ovos-chat-openai-plugin"],
  "memory_module": null
}
```

Each query is sent to the solver as a single message with no prior context.

---

## Custom Memory Plugins

Install any `opm.agents.memory` plugin and reference it by entry point name:

```json
{
  "name": "LongMemory",
  "handlers": ["ovos-chat-openai-plugin"],
  "memory_module": "ovos-memory-plugin-longterm",
  "ovos-memory-plugin-longterm": {
    "db_path": "~/.local/share/mycroft/persona_memory.db"
  }
}
```

---
[← HiveMind](hivemind.md) · [Home](index.md)
