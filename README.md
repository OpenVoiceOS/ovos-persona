# Persona

This repository provides the `PersonaPipeline` for OpenVoiceOS (OVOS), which facilitates managing multiple personas and enables interactive conversations with a virtual assistant. The system is built around the concept of personas, each equipped with solvers to handle specific types of queries. This service allows you to load, register, and interact with personas using a chatbot API.

## Features

- **Multiple Personas**: Manage a list of personas, each defined by a set of question-solving plugins.
- **Conversational**: Summon/Release persona on demand
- **Personalize**: Create your own persona via .json files


## Installation

```bash
pip install ovos-persona
```
### Configuring Personas

Personas are loaded from configuration files, which can either be provided by plugins or user-defined JSON files. 

By default, personas are loaded from the XDG configuration directory, just create .json files under `~/.config/ovos_persona`

Example to use a local OpenAI compatible server, `~/.config/ovos_persona/llm.json`

```json
{
  "name": "My Local LLM",
  "solvers": [
    "ovos-solver-openai-persona-plugin"
  ],
  "ovos-solver-openai-persona-plugin": {
    "api_url": "https://llama.smartgic.io/v1",
    "key": "sk-xxxx",
    "persona": "helpful, creative, clever, and very friendly."
  }
}
```

## Pipeline Usage

The `PersonaService` class manages the overall persona system. It allows you to load personas, handle intents, and interact with personas using the chatbot API.

> **NOT YET FUNCTIONAL** TODO: pending PR: https://github.com/OpenVoiceOS/ovos-core/pull/570

The configuration file can specify:
- The path to persona files (`personas_path`).
- A list of blacklisted personas (`persona_blacklist`) to not load.
- The default persona (`default_persona`).

```json
{
  "persona": {
    "personas_path": "/path/to/personas",
    "persona_blacklist": [
      "persona_to_exclude"
    ],
    "default_persona": "default_persona"
  }
}
```

#### Direct Usage

```python
from ovos_persona import PersonaService

# Initialize the PersonaService
persona_service = PersonaService(config={"personas_path": "/path/to/personas"})

# List all loaded personas
print(persona_service.personas)

# Ask a question to a persona
response = persona_service.chatbox_ask("What is the speed of light?", persona="my_persona")
print(response)
```

Each `Persona` has a name and configuration, and it uses a set of solvers to handle questions. You can interact with a persona by sending a list of messages to the `chat()` method.

```python
from ovos_persona import Persona

# Create a persona instance
persona = Persona(name="my_persona", config={"solvers": ["my_solver_plugin"]})

# Ask a question to the persona
response = persona.chat(messages=[{"role": "user", "content": "What is the capital of France?"}])
print(response)
```

## Events

- **persona:answer**: Sent when a persona provides an answer to a query.
- **persona:summon**: Sent when a persona is summoned.
- **persona:release**: Sent when a persona is released.


## Contributing

Feel free to submit issues or pull requests for any improvements or bug fixes.
