# PersonaService

**Module:** `ovos_persona.PersonaService`

`PersonaService` is simultaneously a `ConfidenceMatcherPipeline` plugin and an `OVOSAbstractApplication`. It acts as a pipeline stage that intercepts utterances, matches persona-management intents, and routes queries to the appropriate `Persona`.

---

## Constructor

```python
from ovos_persona import PersonaService

svc = PersonaService(bus=bus, config=config)
```

`config` is read from `mycroft.conf["intents"]["persona"]` if not provided.

On construction:
1. Loads personas from `personas_path` (user JSON files) and from plugin entry points (`opm.persona`)
2. Trains padatious/padacioso intent matchers for all configured languages
3. Registers bus event handlers

---

## Persona Loading

```python
svc.load_personas(personas_path=None)
```

Two sources are merged, with user files taking priority:

1. **User-defined JSON files** — all `.json` files in `personas_path` (default: `~/.config/ovos_persona/`). If the JSON has a `"name"` field it is used as the persona name; otherwise the filename (without `.json`) is used.

2. **Plugin personas** — discovered via `find_persona_plugins()` (entry point group `opm.persona`). Skipped if `ignore_plugin_personas: true` or if a user file with the same name was already loaded.

Personas in `persona_blacklist` are silently skipped from both sources.

```python
# Register/remove at runtime
svc.register_persona("MyBot", persona_config_dict)
svc.deregister_persona("MyBot")
```

---

## Intent Matching (Pipeline Integration)

`PersonaService` implements all three pipeline confidence levels:

### `match_high(utterances, lang, message)`

Runs the utterance through the language-appropriate padatious/padacioso container. Handles:

- **`summon.intent`** → `persona:summon` — if persona name is in the match entities
- **`ask.intent`** → `persona:query` — if both persona name and query are present and persona exists
- **`list_personas.intent`** → `persona:list`
- **`active_persona.intent`** → `persona:check`
- Release vocabulary → `persona:release` — if a persona is currently active
- **Active persona passthrough** — if a persona is active and no management intent matches, delegates to `match_low`

Minimum confidence is controlled by `min_intent_confidence` (default `0.6`).

### `match_medium(utterances, lang, message)`

Adapt-like keyword fallback for when padatious confidence is insufficient. Checks if any persona name appears in the utterance and combines it with `ask`/`opinion` or `summon` vocabulary matches to produce intent matches.

### `match_low(utterances, lang, message)`

Routes directly to the active persona (or default persona if `handle_fallback: true`). Always returns a match when a persona is available — use as a last-resort stage only.

---

## Persona Name Fuzzy Matching

```python
svc.get_persona("ChatGPT")   # → closest registered persona name
```

Uses `MatchStrategy.PARTIAL_TOKEN_SET_RATIO` with a minimum score of `0.7`. Returns `None` if no persona is close enough. Falls back to the active persona or default persona when `persona` is empty.

---

## Session Management

`PersonaService` supports the OVOS `can_stop` / `stop_session` interface:

```python
svc.can_stop(message)       # True while a streaming response is in progress
svc.stop_session(session)   # Cancel an in-progress streaming query
```

Per-session streaming state is tracked in `self._active_sessions`.

---

## Memory Integration

`PersonaService` listens to bus events to maintain conversation history:

- `recognizer_loop:utterance` → appends `MessageRole.USER` to the active persona's memory
- `speak` → appends `MessageRole.ASSISTANT` to the active persona's memory

This keeps history consistent even when responses span multiple `speak` events.

---

## Intent Files (Locale)

Built-in intents are loaded from `ovos_persona/locale/{lang}/`:

| File | Intent | Description |
|---|---|---|
| `summon.intent` | `persona:summon` | "activate {persona}", "switch to {persona}" |
| `ask.intent` | `persona:query` | "ask {persona} {utterance}" |
| `list_personas.intent` | `persona:list` | "what personas are available" |
| `active_persona.intent` | `persona:check` | "which persona is active" |

Templates use bracket expansion (`[word1|word2]`). Training uses padatious when installed, falling back to padacioso.

---

## Bus Events Handled

| Event | Handler | Description |
|---|---|---|
| `persona:query` | `handle_persona_query` | Route utterance to named persona and speak result |
| `persona:summon` | `handle_persona_summon` | Set active persona |
| `persona:list` | `handle_persona_list` | Speak all persona names |
| `persona:check` | `handle_persona_check` | Speak currently active persona |
| `persona:release` | `handle_persona_release` | Clear active persona |
| `recognizer_loop:utterance` | `handle_utterance` | Record user message in memory |
| `speak` | `handle_speak` | Record assistant message in memory |

## Bus Events Emitted

All speech output uses `self.speak()` / `self.speak_dialog()` from `OVOSAbstractApplication`. Dialog keys:

| Dialog key | When |
|---|---|
| `activated_persona` | Persona summoned |
| `release_persona` | Persona released |
| `active_persona` | Responding to active persona check |
| `no_active_persona` | No persona is active |
| `unknown_persona` | Requested persona not found |
| `no_personas` | No personas are loaded |
| `list_personas` | Prefix before listing persona names |
| `persona_error` | Persona failed to produce an answer |
