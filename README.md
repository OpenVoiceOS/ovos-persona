# OVOS-Persona

`PersonaPipeline` adds multi-persona management to OpenVoiceOS (OVOS). Personas are configurable virtual assistants: each one assigns its own set of solver plugins to answer queries, so you can customize how OVOS handles a conversation.

See [docs/index.md](docs/index.md) for the architecture and API reference.

---

## Quick Start

1. Update the core and install the plugin:
   ```bash
   pip install -U ovos-core>=0.5.1 ovos-persona
   ```
2. Install or update the plugins and skills a persona needs:
   ```bash
   pip install -U skill-wolfie ovos-skill-wikipedia ovos-skill-wikihow skill-wordnet ovos-openai-plugin
   ```
3. Uninstall the ChatGPT fallback skill, since `ovos-persona` replaces it:
   ```bash
   pip uninstall skill-ovos-fallback-chatgpt
   ```
4. Edit `mycroft.conf`. The `"..."` below is a placeholder for your existing pipeline entries, not literal text.
   ```json
   {
     "intents": {
         "persona": {
           "handle_fallback":  true,
           "default_persona": "Remote Llama",
           "short-term-memory": true
         },
         "pipeline": [
             "stop_high",
             "converse",
             "ocp_high",
             "padatious_high",
             "adapt_high",
             "ovos-persona-pipeline-plugin-high",
             "ocp_medium",
             "...",
             "fallback_medium",
             "ovos-persona-pipeline-plugin-low",
             "fallback_low"
       ]
     }
   }
   ```
5. Restart OVOS.
6. Check the logs to confirm the persona loaded without errors:
   ```bash
   cat ~/.local/state/mycroft/skills.log | grep persona
   ```
7. Read the [Persona Intents](#persona-intents) section for the voice commands.

---

## Features

- **Multiple personas**: manage a list of personas, each with its own solver plugins.
- **Dynamic switching**: activate a different persona at any time.
- **Per-session state**: the active persona and conversation memory are tracked per session, so concurrent conversations stay isolated.
- **Short-term memory**: a default short-term memory ships with `ovos-persona` and is always available. Swap it for any `opm.agents.memory` plugin through the `memory_module` config key. See [docs/memory.md](docs/memory.md).
- **Conversational**: personas can handle utterances directly, without a matching skill.
- **Personalize**: create a persona with a simple `.json` file. See [docs/defining-personas.md](docs/defining-personas.md).

---

## Installation

```bash
pip install ovos-persona
```

---

## Persona Intents

The persona service supports voice intents for managing persona interactions. Each intent corresponds to a messagebus event.

### List personas

Example utterances:
- "What personas are available?"
- "Can you list the personas?"
- "What personas can I use?"

### Check the active persona

Example utterances:
- "Who am I talking to right now?"
- "Is there an active persona?"
- "Which persona is in use?"

### Activate a persona

Example utterances:
- "Connect me to {persona}"
- "Enable {persona}"
- "Awaken the {persona} assistant"
- "Start a conversation with {persona}"
- "Let me chat with {persona}"

### Ask a persona a single question

These utterances query a persona directly, without starting an interactive session.

Example utterances:
- "Ask {persona} what they think about {utterance}"
- "What does {persona} say about {utterance}?"
- "Query {persona} for insights on {utterance}"
- "Ask {persona} for their perspective on {utterance}"

### Stop the conversation

Example utterances:
- "Stop the interaction"
- "Terminate persona"
- "Deactivate the chatbot"
- "Go dormant"
- "Enough talking"
- "Shut up"

---

## Pipeline Configuration

When a persona is active, you have two options:
- send every utterance to the persona and ignore all skills, or
- let high-confidence skills match before the persona does.

Where you place `"ovos-persona-pipeline-plugin-high"` in the pipeline decides which behavior you get. `"ovos-persona-pipeline-plugin-low"` handles utterances even when no persona is explicitly active.

#### Option 1: send all utterances to the active persona

With this option, the persona has full control over user utterances. It will most likely fail to perform actions such as playing music, telling the time, or setting alarms. You must explicitly deactivate the persona to use that functionality.

Add the persona pipeline before the `_high` pipeline matchers. The `"..."` below is a placeholder for your existing pipeline entries, not literal text.

```json
{
  "intents": {
      "pipeline": [
          "ovos-persona-pipeline-plugin-high",
          "stop_high",
          "converse",
          "ocp_high",
          "padatious_high",
          "adapt_high",
          "...",
          "fallback_low"
    ]
  }
}
```

#### Option 2: let high-confidence skills match before using the persona

With this option, skills can still trigger even when a persona is active, so not every answer comes from the persona.

Add the persona pipeline after the `_high` pipeline matchers. The `"..."` below is a placeholder for your existing pipeline entries, not literal text.

```json
{
  "intents": {
      "pipeline": [
          "stop_high",
          "converse",
          "ocp_high",
          "padatious_high",
          "adapt_high",
          "ovos-persona-pipeline-plugin-high",
          "ocp_medium",
          "...",
          "fallback_low"
    ]
  }
}
```

#### Extra option: as a fallback skill

You can configure `ovos-persona` to handle utterances when all skills fail, even if no persona is active. This is handled through `"ovos-persona-pipeline-plugin-low"`. The `"..."` below is a placeholder for your existing pipeline entries, not literal text.

```json
{
  "intents": {
      "persona": {
        "handle_fallback":  true,
        "default_persona": "Remote Llama"
      },
      "pipeline": [
          "...",
          "fallback_medium",
          "ovos-persona-pipeline-plugin-low",
          "fallback_low"
    ]
  }
}
```

`"ovos-persona-pipeline-plugin-low"` is meant to replace [OpenVoiceOS/ovos-skill-fallback-chatgpt](https://github.com/OpenVoiceOS/ovos-skill-fallback-chatgpt).

---

## Creating a Persona

Personas are configured with JSON files. A persona can come from:
1. a plugin (for example, the [OpenVoiceOS/ovos-openai-plugin](https://github.com/OpenVoiceOS/ovos-openai-plugin)), or
2. a user-defined JSON file in `~/.config/ovos_persona`.

Personas rely on [solver plugins](https://openvoiceos.github.io/ovos-technical-manual/solvers/), which try to answer a query in sequence until one succeeds.

Example: a persona using a local OpenAI-compatible server. Save this as `~/.config/ovos_persona/llm.json`:
```json
{
  "name": "My Local LLM",
  "solvers": [
    "ovos-solver-openai-plugin"
  ],
  "ovos-solver-openai-plugin": {
    "api_url": "https://llama.smartgic.io/v1",
    "key": "sk-xxxx",
    "system_prompt": "helpful, creative, clever, and very friendly."
  }
}
```

A persona does not need an LLM. Simpler solvers work too, even without a GPU.

Example: OldSchoolBot, a persona built from non-LLM solvers.
```json
{
  "name": "OldSchoolBot",
  "solvers": [
    "ovos-solver-wikipedia-plugin",
    "ovos-solver-ddg-plugin",
    "ovos-solver-plugin-wolfram-alpha",
    "ovos-solver-wordnet-plugin",
    "ovos-solver-rivescript-plugin",
    "ovos-solver-failure-plugin"
  ],
  "ovos-solver-plugin-wolfram-alpha": {"appid": "Y7353-xxxxxx"}
}
```
Behavior:
- Searches online sources such as Wikipedia and Wolfram Alpha.
- Falls back to offline word lookups through WordNet.
- Uses a local chatbot (RiveScript) for chitchat.
- The "failure" solver catches errors so the persona always returns a response.

---

## HiveMind Integration

This project includes a native [hivemind-plugin-manager](https://github.com/JarbasHiveMind/hivemind-plugin-manager) integration for interoperability with the HiveMind ecosystem.

- **Agent protocol**: [hivemind-persona-agent-plugin](https://github.com/JarbasHiveMind/hivemind-persona-agent-plugin) lets HiveMind satellites connect directly to a persona. See [docs/hivemind.md](docs/hivemind.md).

---

## Related Projects

- [OpenVoiceOS/ovos-persona-server](https://github.com/OpenVoiceOS/ovos-persona-server) — standalone server for persona-based conversations.
- [TigreGotico/ovos-persona-marketplace](https://github.com/TigreGotico/ovos-persona-marketplace) — a marketplace for sharing persona configurations.
- [JarbasHiveMind/hivemind-persona-agent-plugin](https://github.com/JarbasHiveMind/hivemind-persona-agent-plugin) — HiveMind agent protocol plugin for `ovos-persona`.
- [OpenVoiceOS/ovos-openai-plugin](https://github.com/OpenVoiceOS/ovos-openai-plugin) — OpenAI-compatible solver plugin.

---

## Contributing

Found a bug or have an idea? Open an issue or submit a pull request.

---

## Credits

Developed by [TigreGótico](https://tigregotico.pt) for
[OpenVoiceOS](https://openvoiceos.org).

[![NGI0 Commons Fund](./ngi.png)](https://nlnet.nl/project/OpenVoiceOS)

This project was funded through the [NGI0 Commons Fund](https://nlnet.nl/commonsfund),
a fund established by [NLnet](https://nlnet.nl) with financial support from the
European Commission's [Next Generation Internet](https://ngi.eu) programme, under
the aegis of [DG Communications Networks, Content and Technology](https://commission.europa.eu/about-european-commission/departments-and-executive-agencies/communications-networks-content-and-technology_en)
under grant agreement No [101135429](https://cordis.europa.eu/project/id/101135429).
