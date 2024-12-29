import dataclasses
import json
import os
from typing import Dict, Any, List

from hivemind_bus_client.message import HiveMessage, HiveMessageType
from hivemind_core.protocol import AgentProtocol
from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from ovos_persona import Persona


@dataclasses.dataclass()
class PersonaProtocol(AgentProtocol):
    bus: MessageBusClient = dataclasses.field(default_factory=FakeBus)
    config: Dict[str, Any] = dataclasses.field(default_factory=dict)
    sessions: Dict[str, List[Dict[str, str]]] = dataclasses.field(default_factory=dict)
    persona: Persona = None

    def __post_init__(self):
        if not self.persona:
            persona_json = self.config.get("persona")
            if not persona_json:
                persona = {
                    "name": "ChatGPT",
                    "solvers": [
                        "ovos-solver-openai-persona-plugin"
                    ],
                    "ovos-solver-openai-persona-plugin": {
                        "api_url": "https://llama.smartgic.io/v1",
                        "key": "sk-xxxx",
                        "persona": "helpful, creative, clever, and very friendly."
                    }
                }
                name = persona.get("name")
            else:
                with open(persona_json) as f:
                    persona = json.load(f)
                name = persona.get("name") or os.path.basename(persona_json)
            self.persona = Persona(name=name, config=persona)

        LOG.debug("registering internal OVOS bus handlers")
        self.bus.on("recognizer_loop:utterance", self.handle_utterance)  # catch all

    def handle_utterance(self, message: Message):
        """
        message (Message): mycroft bus message object
        """
        utt = message.data["utterances"][0]

        sess = SessionManager.get(message)

        # track msg history
        if sess.session_id not in self.sessions:
            self.sessions[sess.session_id] = []
        self.sessions[sess.session_id].append({"role": "user", "content": utt})

        answer = self.persona.chat(self.sessions[sess.session_id], lang=sess.lang).strip()
        peer = message.context["source"]
        client = self.clients[peer]

        msg = HiveMessage(
            HiveMessageType.BUS,
            source_peer=self.hm_protocol.peer,
            target_peers=[peer],
            payload=message.reply("speak", {"utterance": answer}),
        )
        client.send(msg)
        self.sessions[sess.session_id].append({"role": "assistant", "content": answer})
