# OVOS-Persona

The **`PersonaPipeline`** brings multi-persona management to OpenVoiceOS (OVOS), enabling interactive conversations with virtual assistants. 🎙️ With personas, you can customize how queries are handled by assigning specific solvers to each persona.  

---

## 🚀 TLDR - Quick Start

- update core and install persona
    ```bash
    pip install -U ovos-core>=0.5.1 ovos-persona
    ```
- install/update plugins and skills
    ```bash
    pip install -U skill-wolfie ovos-skill-wikipedia ovos-skill-wikihow skill-wordnet ovos-openai-plugin
    ```
- uninstall chatgpt skill
    ```bash
    pip uninstall skill-ovos-fallback-chatgpt
    ```
- edit mycroft.conf
    > ⚠️ don't just copy paste, the `"..."` is a placeholder and invalid. adjust to your existing pipeline config
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
- restart ovos
- check logs to see persona loading, ensure there are no errors
    ```bash
    cat ~/.local/state/mycroft/skills.log | grep persona
    ```
- read the intents section below
- 🎉
  
---

## ✨ Features

- **🧑‍💻 Multiple Personas**: Manage a list of personas, each with its unique solvers.  
- **🔄 Dynamic Switching**: Seamlessly switch between personas as needed.  
- **💬 Conversational**: Let personas handle utterances directly for richer interaction.  
- **🎨 Personalize**: Create your own personas with simple `.json` files.

---

## 🛠️ Installation

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


## 📖  Pipeline Configuration

When a persona is active you have 2 options:
- send all utterances to the persona and ignore all skills
- let high confidence skills match before using persona

Where to place `"ovos-persona-pipeline-plugin-high"` in your pipeline depends on the desired outcome

Additionally, you have `"ovos-persona-pipeline-plugin-low"` to handle utterances even when a persona isnt explicitly active


##### Option 1: send all utterances to active persona

In this scenario the persona will most likely fail to perform actions like playing music, telling the time and setting alarms. 

You will need to explicitly deactivate a persona to use that functionality, the persona has **full control** over the user utterances

Add the persona pipeline to your mycroft.conf **before** the `_high` pipeline matchers

> ⚠️ don't just copy paste, the `"..."` is a placeholder and invalid. adjust to your existing pipeline config
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

##### Option 2: let high confidence skills match before using persona

With this option you still allow skills to trigger even when a persona is active, not all answers are handled by the persona in this case

Add the persona pipeline to your mycroft.conf **after** the `_high` pipeline matchers

> ⚠️ don't just copy paste, the `"..."` is a placeholder and invalid. adjust to your existing pipeline config
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

##### Extra Option: as fallback skill

You can configure ovos-persona to handle utterances when all skills fail even if a persona is not active, this is handled via `"ovos-persona-pipeline-plugin-low"`

> ⚠️ don't just copy paste, the `"..."` is a placeholder and invalid. adjust to your existing pipeline config

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

> ⚠️ `"ovos-persona-pipeline-plugin-low"` is meant to replace [ovos-skill-fallback-chatgpt](https://github.com/OpenVoiceOS/ovos-skill-fallback-chatgpt)

---

## 🔧 Creating a Persona

Personas are configured using JSON files. These can be:  
1️⃣ Provided by **plugins** (e.g., [OpenAI plugin](https://github.com/OpenVoiceOS/ovos-openai-plugin/pull/12)).  
2️⃣ Created as **user-defined JSON files** in `~/.config/ovos_persona`.  

Personas rely on [solver plugins](https://openvoiceos.github.io/ovos-technical-manual/solvers/), which attempt to answer queries in sequence until a response is found.  

🛠️ **Example:** Using a local OpenAI-compatible server.  
Save this in `~/.config/ovos_persona/llm.json`:  
```json
{
  "name": "My Local LLM",
  "solvers": [
    "ovos-solver-openai-plugin"
  ],
  "ovos-solver-openai-plugin": {
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

## 📡 HiveMind Integration

This project includes a native [hivemind-plugin-manager](https://github.com/JarbasHiveMind/hivemind-plugin-manager) integration, providing seamless interoperability with the HiveMind ecosystem.

- **Agent Protocol**: Provides `hivemind-persona-agent-plugin` allowing to connect satellites directly to a persona
  

---


## 🤝 Contributing

Got ideas or found bugs?  
Submit an issue or create a pull request to help us improve! 🌟  
