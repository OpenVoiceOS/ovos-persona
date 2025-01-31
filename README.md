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

## 🗣️ Persona Intents

The Persona Service supports a set of core voice intents to manage persona interactions seamlessly. These intents correspond to the **messagebus events** but are designed for **voice-based activation**.  

These intents provide **out-of-the-box functionality** for controlling the Persona Service, ensuring smooth integration with the conversational pipeline and enhancing user experience.

### **List Personas**

**Example Utterances**:
- "What personas are available?"
- "Can you list the personas?"
- "What personas can I use?"

### **Check Active Persona**

**Example Utterances**:

- "Who am I talking to right now?"
- "Is there an active persona?"
- "Which persona is in use?"

### **Activate a Persona**

**Example Utterances**:
- "Connect me to {persona}"  
- "Enable {persona}"  
- "Awaken the {persona} assistant"  
- "Start a conversation with {persona}"  
- "Let me chat with {persona}"  


### **Single-Shot Persona Questions**

Enables users to query a persona directly without entering an interactive session.  

**Example Utterances**:
- "Ask {persona} what they think about {utterance}"  
- "What does {persona} say about {utterance}?"  
- "Query {persona} for insights on {utterance}"  
- "Ask {persona} for their perspective on {utterance}"  


### **Stop Conversation**

**Example Utterances**:
- "Stop the interaction"  
- "Terminate persona"  
- "Deactivate the chatbot"  
- "Go dormant"  
- "Enough talking"  
- "Shut up"  

---

## 📨 Messagebus Events

You can control the persona service via bus messages

- **`persona:query`**: Submit a query to a persona.  
- **`persona:summon`**: Summon a persona.  
- **`persona:release`**: Release a persona.  

---

## 📡 HiveMind Integration

This project includes a native [hivemind-plugin-manager](https://github.com/JarbasHiveMind/hivemind-plugin-manager) integration, providing seamless interoperability with the HiveMind ecosystem.

- **Agent Protocol**: Provides `hivemind-persona-agent-plugin` allowing to connect satellites directly to a persona
  

---

## 🛠️ Pipeline Usage

When a persona is active you have 2 options:
- send all utterances to the persona and ignore all skills
- let high confidence skills match before using persona

Where to place `"ovos-persona-pipeline-plugin-high"` in your pipeline depends on the desired outcome

Additionally, you have `"ovos-persona-pipeline-plugin-low"` to handle utterances even when a persona isnt explicitly active

##### Option 1: send all utterances to active persona

In this scenario the persona will most likely fail to perform actions like playing music, telling the time and setting alarms. 

You will need to explicitly deactivate a persona to use that functionality, the persona has **full control** over the user utterances

Add the persona pipeline to your mycroft.conf **before** the `_high` pipeline matchers

```json
{
  "intents": {
      "persona": {"handle_fallback":  true},
      "pipeline": [
          "ovos-persona-pipeline-plugin-high",
          "stop_high",
          "converse",
          "ocp_high",
          "padatious_high",
          "adapt_high",
          "ocp_medium",
          "fallback_high",
          "stop_medium",
          "adapt_medium",
          "padatious_medium",
          "adapt_low",
          "common_qa",
          "fallback_medium",
          "ovos-persona-pipeline-plugin-low",
          "fallback_low"
    ]
  }
}
```

##### Option 2: let high confidence skills match before using persona

With this option you still allow skills to trigger even when a persona is active, not all answers are handled by the persona in this case

Add the persona pipeline to your mycroft.conf **after** the `_high` pipeline matchers

```json
{
  "intents": {
      "persona": {"handle_fallback":  true},
      "pipeline": [
          "stop_high",
          "converse",
          "ocp_high",
          "padatious_high",
          "adapt_high",
          "ovos-persona-pipeline-plugin-high",
          "ocp_medium",
          "fallback_high",
          "stop_medium",
          "adapt_medium",
          "padatious_medium",
          "adapt_low",
          "common_qa",
          "fallback_medium",
          "ovos-persona-pipeline-plugin-low",
          "fallback_low"
    ]
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



## 🤝 Contributing

Got ideas or found bugs?  
Submit an issue or create a pull request to help us improve! 🌟  
