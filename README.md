# OVOS-Persona

The **`PersonaPipeline`** brings multi-persona management to OpenVoiceOS (OVOS), enabling interactive conversations with virtual assistants. 🎙️ With personas, you can customize how queries are handled by assigning specific solvers to each persona.  

---

## ✨ Features

- **🧑‍💻 Multiple Personas**: Manage a list of personas, each with its unique solvers.  
- **🔄 Dynamic Switching**: Seamlessly switch between personas as needed.  
- **💬 Conversational**: Let personas handle utterances directly for richer interaction.  
- **🎨 Personalize**: Create your own personas with simple `.json` files.

---

## 🚀 Installation

```bash
pip install ovos-persona
```

---

## 🔧 Configuring Personas

Personas are configured using JSON files. These can be:  
1️⃣ Provided by **plugins** (e.g., [OpenAI plugin](https://github.com/OpenVoiceOS/ovos-solver-openai-persona-plugin/pull/12)).  
2️⃣ Created as **user-defined JSON files** in `~/.config/ovos_persona`.  

Personas rely on [solver plugins](https://openvoiceos.github.io/ovos-technical-manual/solvers/), which attempt to answer queries in sequence until a response is found.  

🛠️ **Example:** Using a local OpenAI-compatible server.  
Save this in `~/.config/ovos_persona/llm.json`:  
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

> 💡 **Tip**: Personas don't have to use LLMs! Even without a GPU, you can leverage simpler solvers.  

🛠️ **Example:** OldSchoolBot:  
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
**Behavior**:
- 🌐 Searches online (Wikipedia, Wolfram Alpha, etc.).  
- 📖 Falls back to offline word lookups via WordNet.  
- 🤖 Uses local chatbot (RiveScript) for chitchat.  
- ❌ The "failure" solver ensures errors are gracefully handled and we always get a response.

---

## 🛠️ Pipeline Usage

> 🚧 **NOT YET FUNCTIONAL**: pending PR: https://github.com/OpenVoiceOS/ovos-core/pull/570 🚧 

To integrate the Persona Pipeline, include the plugins in your `mycroft.conf` configuration:  

- `"ovos-persona-pipeline-plugin-high"` → just before `"fallback_high"`.  
- `"ovos-persona-pipeline-plugin-low"` → just before `"fallback_low"`.  

```json
{
  "intents": {
    "pipeline": [
      "...",
      "adapt_high",
      "...",
      "ovos-persona-pipeline-plugin-high",
      "...",
      "padatious_medium",
      "...",
      "ovos-persona-pipeline-plugin-low",
      "fallback_low"
    ],
    "ovos-persona-pipeline-plugin": {
      "personas_path": "/path/to/personas",
      "persona_blacklist": ["persona_to_exclude"],
      "default_persona": "default_persona"
    }
  }
}
```

> **ℹ️ Note**: No "medium" plugin exists for this pipeline.  

---

## 🐍 Python Usage


```python
from ovos_persona import PersonaService

# Initialize the PersonaService
persona_service = PersonaService(config={"personas_path": "/path/to/personas"})

# List all loaded personas
print(persona_service.personas)

# Ask a persona a question
response = persona_service.chatbox_ask("What is the speed of light?", persona="my_persona")
print(response)
```

Each `Persona` has a name and configuration, and it uses a set of solvers to handle questions. You can interact with a persona by sending a list of messages to the `chat()` method.

```python
from ovos_persona import Persona

# Create a persona instance
persona = Persona(name="my_persona", config={"solvers": ["my_solver_plugin"]})

# Ask the persona a question
response = persona.chat(messages=[{"role": "user", "content": "What is the capital of France?"}])
print(response)
```

---

## 📡 Messagebus Events

- **`persona:query`**: Submit a query to a persona.  
- **`persona:summon`**: Summon a persona.  
- **`persona:release`**: Release a persona.  

---

## 🤝 Contributing

Got ideas or found bugs?  
Submit an issue or create a pull request to help us improve! 🌟  

--- 

This updated README is designed to be approachable and highlights key functionality with subtle use of emojis. Let me know if you'd like any changes!
