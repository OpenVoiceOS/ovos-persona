# Set up personas

Each section gives the setup, the steps and the output of a real run. The chat
model was a small public demo model (`qwen2.5:7b`). A larger model gives
better answers, and the memory and the routing behave the same.

- [Make a persona remember what you said](#make-a-persona-remember-what-you-said)
- [Give each device its own persona](#give-each-device-its-own-persona)
- [Run several personas on one server](#run-several-personas-on-one-server)
- [Move from solver plugins to agent engines](#move-from-solver-plugins-to-agent-engines)
- [Known limits](#known-limits)

Install the packages:

```bash
pip install --pre ovos-persona ovos-openai-plugin
```

The scripts use a `personas` directory in the working directory. Change
`api_url` to your own OpenAI-compatible server.

---

## Make a persona remember what you said

To make a persona use what you said a few turns ago, use the default
short-term memory. It keeps the last messages of each session in RAM. Each
device has its own session, so each device has its own history.

1. Save the persona as `personas/helper.json`:

    ```json
    {
      "name": "helper",
      "handlers": ["ovos-chat-openai-plugin"],
      "ovos-chat-openai-plugin": {
        "api_url": "https://llama.smartgic.io/v1",
        "key": "sk-none",
        "model": "qwen2.5:7b",
        "system_prompt": "You are a home assistant. Answer in at most fifteen words."
      },
      "memory_module": "ovos-agents-short-term-memory-plugin",
      "ovos-agents-short-term-memory-plugin": {"max_history": 6}
    }
    ```

    `max_history` counts messages, not exchanges. The persona stores each
    exchange as a question and an answer. A value of `6` gives the model the
    last three exchanges and the new question. When the limit cuts an exchange
    in two, the persona drops the answer that has no question.

2. Run this script. It sends the `persona:query` message that `ovos-core`
   sends when the persona pipeline matches an utterance. The persona records
   each exchange when it has finished the answer:

    ```python
    from ovos_bus_client.message import Message
    from ovos_bus_client.session import Session
    from ovos_persona import PersonaService
    from ovos_utils.fakebus import FakeBus

    bus = FakeBus()
    svc = PersonaService(bus=bus, config={"personas_path": "personas"})
    spoken = []
    bus.on("speak", lambda msg: spoken.append(msg.data["utterance"]))


    def say(text, device):
        sess = Session(device)
        sess.persona_id = "helper"
        spoken.clear()
        bus.emit(Message("persona:query", {"utterance": text}, {"session": sess.serialize()}))
        print(f"{device}> {text}\n  {' '.join(spoken)}")


    say("My name is Rita. I parked on level 3.", "living-room")
    say("Which level did I park on? Answer with the number only.", "living-room")
    say("Where did I park? If you do not know, say UNKNOWN.", "garage")
    for topic in ("the weather", "music", "cooking"):
        say(f"Tell me one fact about {topic}.", "living-room")
    say("Where did I park? If you do not know, say UNKNOWN.", "living-room")
    ```

Output:

```
living-room> My name is Rita. I parked on level 3.
  Hello Rita, your car is parked on Level 3, parking spot 12 if needed.
living-room> Which level did I park on? Answer with the number only.
  3
garage> Where did I park? If you do not know, say UNKNOWN.
  UNKNOWN. Can you provide more context or details about your vehicle and location?
living-room> Tell me one fact about the weather.
  Today's forecast shows a high chance of scattered showers in your area.
living-room> Tell me one fact about music.
  The Beatles released their iconic album "Sgt. Pepper's Lonely Hearts Club Band" in 1967.
living-room> Tell me one fact about cooking.
  Boiling water is a great way to cook eggs, with perfect results every time.
living-room> Where did I park? If you do not know, say UNKNOWN.
  UNKNOWN
```

The living room recalls the level. The garage is a different session and has
no history. After three more exchanges, the parking level is out of the
window and the living room forgets it.

The short-term memory is in RAM, so a restart clears it. For memory that
survives a restart, set `memory_module` to a plugin from
[ovos-memory-plugins](https://github.com/OpenVoiceOS/ovos-memory-plugins/blob/dev/docs/set-up-memory.md).
These plugins add system messages to the prompt, so set
`"allow_system_prompts": true` in the `ovos-chat-openai-plugin` block. Without
it, the plugin removes the recalled context before the request.

| Problem | Cause | Fix |
|---|---|---|
| The persona forgets after one or two turns | `max_history` is too small | Increase `max_history`. It counts messages, two for each exchange |
| The persona forgets everything after a restart | The default memory is in RAM | Use a persistent plugin, for example `ovos-memory-plugin-entity` |
| A memory plugin has no effect | `allow_system_prompts` is off | Set `"allow_system_prompts": true` |

---

## Give each device its own persona

To use a different persona in each room of one OVOS install, summon a
persona on each device. A summon command sets `persona_id` on the session of
the device that heard it. Other devices keep their own persona, or none.

1. Save two personas, `personas/ada.json` and `personas/bo.json`. This is
   `ada.json`. `bo.json` is the same, with the name `bo` and the system prompt
   changed to the name Bo:

    ```json
    {
      "name": "ada",
      "handlers": ["ovos-chat-openai-plugin"],
      "ovos-chat-openai-plugin": {
        "api_url": "https://llama.smartgic.io/v1",
        "key": "sk-none",
        "model": "qwen2.5:7b",
        "system_prompt": "Your name is Ada. You answer in at most fifteen words. When asked your name, say Ada."
      }
    }
    ```

2. Run this script. It sends the voice commands of two devices through the
   persona intent matcher:

    ```python
    from ovos_bus_client.message import Message
    from ovos_bus_client.session import Session
    from ovos_persona import PersonaService
    from ovos_utils.fakebus import FakeBus

    svc = PersonaService(bus=FakeBus(), config={"personas_path": "personas"})


    def heard(text, sess):
        msg = Message("recognizer_loop:utterance", {"utterances": [text]}, {"session": sess.serialize()})
        match = svc.match_high([text], "en-US", msg)
        return match.updated_session if match else sess


    kitchen = heard("talk to ada", Session("kitchen"))
    bedroom = heard("talk to bo", Session("bedroom"))
    for sess in (kitchen, bedroom, Session("hall")):
        print(sess.session_id, "->", sess.persona_id)
    for sess in (kitchen, bedroom):
        print(sess.session_id, "says:", " ".join(svc.query("What is your name? Answer with your name only.",
                                                         sess.persona_id, sess)))
    kitchen = heard("stop talking to ada", kitchen)
    print("kitchen after release ->", kitchen.persona_id)
    ```

Output:

```
kitchen -> ada
bedroom -> bo
hall -> None
kitchen says: Ada.
bedroom says: Bo.
kitchen after release -> None
```

The persona lives in the session, not in the service. A device that sends its
session with each message, such as a HiveMind satellite, keeps its persona
until a release command. A client can also set `persona_id` in the session it
sends, with no voice command.

| Problem | Cause | Fix |
|---|---|---|
| All devices switch persona together | The devices share one session id | Give each device its own session id |
| The summon does nothing | The name does not match a loaded persona | Say the name as it is in the persona file. Check the log for `Failed to load` |

---

## Run several personas on one server

To reach several personas over HTTP from apps that speak the OpenAI or
Ollama API, run `ovos-persona-server`. It loads every persona in a directory.
The `model` field of each request selects the persona, and the `user` field
selects the memory of one person.

The setup and a measured run are in the server documentation:
[several personas on one server](https://github.com/OpenVoiceOS/ovos-persona-server/blob/dev/docs/multi-persona.md).

---

## Move from solver plugins to agent engines

If you maintain a solver plugin, or a persona that lists solver plugins,
move to the agent engine classes. Solver plugins still load and answer.
Each one logs a deprecation warning. Plugins that you write use the agent
engine classes.

| Solver base class | Agent base class | Method to implement |
|---|---|---|
| `QuestionSolver` | `ChatEngine` | `continue_chat(messages, session_id, lang, units, tools)` |
| `ChatMessageSolver` | `ChatEngine` | `continue_chat(messages, session_id, lang, units, tools)` |
| `CorpusSolver`, `QACorpusSolver` | `RetrievalEngine` | `query(query, lang, k)` |

The solver and agent classes are in `ovos-plugin-manager`. The agent classes are in
`ovos_plugin_manager.templates.agents`.

This script runs a solver and its port side by side:

```python
from typing import List, Optional

from ovos_plugin_manager.templates.agents import AgentMessage, ChatEngine, MessageRole
from ovos_plugin_manager.templates.solvers import QuestionSolver


class EchoSolver(QuestionSolver):
    def get_spoken_answer(self, query, lang=None, units=None):
        return f"you said {query}"


class EchoEngine(ChatEngine):
    def continue_chat(self, messages: List[AgentMessage], session_id: str = "default",
                      lang: Optional[str] = None, units: Optional[str] = None,
                      tools=None) -> AgentMessage:
        return AgentMessage(MessageRole.ASSISTANT, f"you said {messages[-1].content}")


print("solver:", EchoSolver().spoken_answer("hello", lang="en-US"))
reply = EchoEngine().continue_chat([AgentMessage(MessageRole.USER, "hello")], session_id="kitchen")
print("engine:", reply.content)
```

Output, with the log lines shortened:

```
WARNING - Deprecation version=3.0.0. ... ovos_plugin_manager.templates.solvers has been deprecated and will be removed in the next major release.
WARNING - Deprecation version=3.0.0. ... QuestionSolver has been deprecated and will be removed in the next major release. Please migrate your code to use ChatEngine / RetrievalEngine
solver: you said hello
engine: you said hello
```

The `version` in the warning is the next major version of the installed
`ovos-plugin-manager`. It does not state when the class goes away. A `ChatEngine` gets the full message list and the
session id, so it can use the persona memory. A `QuestionSolver` gets only the
last question.

In a persona file, list the entry point names. The table gives the names
for the retrieval plugins:

| Name that does not load | Entry point name |
|---|---|
| `ovos-solver-wikipedia-plugin` | `ovos-wikipedia-plugin` |
| `ovos-solver-ddg-plugin` | `ovos-ddg-plugin` |
| `ovos-solver-plugin-wolfram-alpha` | `ovos-wolfram-alpha-plugin` |
| `ovos-solver-wordnet-plugin` | `ovos-wordnet-plugin` |
| `ovos-solver-openai-plugin` | `ovos-chat-openai-plugin` |

A persona with one unknown or uninstalled name does not load. The log says
`Failed to load '<persona>': '<name>' not installed`.

---

## Known limits

- `max_history` counts messages. The persona stores each exchange as two
  messages. When the limit cuts an exchange in two, the persona drops the
  answer that has no question.
- The default short-term memory is in RAM. A restart clears it.
- `PersonaService.query()` does not record history. The `persona:query` handler
  records each exchange it answers, as one user message and one assistant message.
- `ovos-chat-openai-plugin` removes system messages unless
  `allow_system_prompts` is `true`. Memory plugins that add context as a
  system message have no effect without it.

---
[← Defining personas](defining-personas.md) · [Home](index.md)
