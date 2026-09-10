# ovos-persona

`ovos-persona` is a pipeline plugin that routes utterances to named AI "personas": configurable combinations of LLM, solver, and retrieval plugins. A persona gives OVOS an alternative response personality, beyond normal intent matching.

---

## Concepts

- **Persona**: a named configuration that specifies an ordered list of utterance handler plugins (LLMs, solvers, RAG engines). Each persona has its own handler priority order and optional short-term memory.
- **PersonaService**: the pipeline stage that loads all personas, matches persona-management intents (`summon`, `ask`, `list`, `release`), and routes utterances to the active persona.
- **Active persona**: when a user summons a persona by name, all subsequent utterances in that session are routed directly to it, bypassing the normal intent pipeline, until released.
- **Default persona**: a fallback persona used when `handle_fallback: true` is set in config, allowing the persona system to act as the last-resort pipeline stage.

---

## Architecture

```
Pipeline (ConfidenceMatcherPipeline)
    │
    └── PersonaService
            │
            ├── match_high()     ← padatious/padacioso intent matching
            │       └── persona:summon / persona:ask / persona:list / persona:check / persona:release
            │
            ├── match_medium()   ← keyword/voc matching fallback
            │
            └── match_low()      ← active persona passthrough (or default persona if handle_fallback)
                    │
                    └── Persona.stream()
                            └── QuestionSolversService
                                    ├── ChatEngine / MultimodalChatEngine   (LLMs)
                                    ├── ChatMessageSolver                    (chat solvers)
                                    ├── QuestionSolver                       (Q&A solvers)
                                    └── RetrievalEngine / DocumentIndexer    (RAG)
```

---

## Navigation

| Document | Contents |
|---|---|
| [persona-service.md](persona-service.md) | `PersonaService`: pipeline integration, intent matching, bus events |
| [persona.md](persona.md) | `Persona` class: solvers, memory, chat/stream API |
| [solvers.md](solvers.md) | `QuestionSolversService`: plugin types, ordering, completion |
| [memory.md](memory.md) | `BasicShortTermMemory`: session history, context building |
| [hivemind.md](hivemind.md) | `PersonaProtocol`: HiveMind agent integration |
| [defining-personas.md](defining-personas.md) | Persona JSON format, file locations, plugin entry points |

---

## Quick Start

```python
from ovos_persona import PersonaService
from ovos_utils.fakebus import FakeBus

svc = PersonaService(bus=FakeBus(), config={
    "default_persona": "MyChatBot",
    "personas_path": "~/.config/ovos_persona"
})

# Query a persona directly
for sentence in svc.query("what is the speed of light", "MyChatBot"):
    print(sentence)
```

---

## Entry Points

| Entry point group | Name | Class |
|---|---|---|
| `opm.pipeline` | `ovos-persona-pipeline-plugin` | `PersonaService` |
| `opm.agents.memory` | `ovos-agents-short-term-memory-plugin` | `BasicShortTermMemory` |
| `hivemind.agent.protocol` | `hivemind-persona-agent-plugin` | `PersonaProtocol` |

---

## Package Layout

```
ovos_persona/
├── __init__.py    # Persona, PersonaService
├── solvers.py     # QuestionSolversService, get_utterance_handler_plugins
├── memory.py      # BasicShortTermMemory
└── hpm.py         # PersonaProtocol (HiveMind integration)
```

---

## Configuration (`mycroft.conf`)

```json
{
  "intents": {
    "persona": {
      "personas_path": "~/.config/ovos_persona",
      "default_persona": "MyChatBot",
      "handle_fallback": false,
      "ignore_plugin_personas": false,
      "persona_blacklist": [],
      "min_intent_confidence": 0.6,
      "intent_cache": "~/.local/share/mycroft/intent_cache"
    }
  }
}
```

| Key | Default | Description |
|---|---|---|
| `personas_path` | XDG config `ovos_persona/` | Directory for user-defined persona JSON files |
| `default_persona` | first loaded | Persona to use when none is active |
| `handle_fallback` | `false` | If `true`, route all unmatched utterances to the default persona |
| `ignore_plugin_personas` | `false` | If `true`, only load user-defined JSON personas |
| `persona_blacklist` | `[]` | Persona names (or plugin names) to skip when loading |
| `min_intent_confidence` | `0.6` | Minimum padatious score to act on an intent match |
| `intent_cache` | XDG data `intent_cache/` | Directory for padatious intent cache |
