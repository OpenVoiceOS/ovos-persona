import json
import os
from os.path import dirname
from typing import Optional, Dict, List, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_config_save_path
from ovos_plugin_manager.persona import find_persona_plugins
from ovos_plugin_manager.solvers import find_question_solver_plugins
from ovos_plugin_manager.templates.pipeline import PipelineStageMatcher, IntentHandlerMatch, ConfidenceMatcherPipeline
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_workshop.app import OVOSAbstractApplication

from ovos_persona.solvers import QuestionSolversService


class Persona:
    def __init__(self, name, config, blacklist=None):
        blacklist = blacklist or []
        self.name = name
        self.config = config
        persona = config.get("solvers") or ["ovos-solver-failure-plugin"]
        plugs = {}
        for plug_name, plug in find_question_solver_plugins().items():
            if plug_name not in persona or plug_name in blacklist:
                plugs[plug_name] = {"enabled": False}
            else:
                plugs[plug_name] = config.get(plug_name) or {"enabled": True}
        self.solvers = QuestionSolversService(config=plugs)

    def __repr__(self):
        return f"Persona({self.name}:{list(self.solvers.loaded_modules.keys())})"

    def chat(self, messages: list = None, lang: str = None) -> str:
        # TODO - message history solver
        # messages = [
        #    {"role": "system", "content": "You are a helpful assistant."},
        #    {"role": "user", "content": "Knock knock."},
        #    {"role": "assistant", "content": "Who's there?"},
        #    {"role": "user", "content": "Orange."},
        # ]
        prompt = messages[-1]["content"]
        return self.solvers.spoken_answer(prompt, lang)


class PersonaService(PipelineStageMatcher, OVOSAbstractApplication):
    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        config = config or Configuration().get("persona", {})
        OVOSAbstractApplication.__init__(
            self, bus=bus or FakeBus(), skill_id="persona.openvoiceos",
            resources_dir=f"{dirname(__file__)}")
        PipelineStageMatcher.__init__(self, bus, config)
        self.personas = {}
        self.blacklist = self.config.get("persona_blacklist") or []
        self.load_personas(self.config.get("personas_path"))
        self.add_event('persona:answer', self.handle_persona_answer)

    @property
    def default_persona(self) -> Optional[str]:
        persona = self.config.get("default_persona")
        if not persona and self.personas:
            persona = list(self.personas.keys())[0]
        return persona

    def load_personas(self, personas_path: Optional[str] = None):
        personas_path = personas_path or get_xdg_config_save_path("ovos_persona")
        LOG.info(f"Personas path: {personas_path}")
        # load personas provided by packages
        for name, persona in find_persona_plugins().items():
            if name in self.blacklist:
                continue
            self.personas[name] = Persona(name, persona)

        # load user defined personas
        os.makedirs(personas_path, exist_ok=True)
        for p in os.listdir(personas_path):
            if not p.endswith(".json"):
                continue
            name = p.replace(".json", "")
            if name in self.blacklist:
                continue
            with open(f"{personas_path}/{p}") as f:
                persona = json.load(f)
            self.personas[name] = Persona(name, persona)

    def register_persona(self, name, persona):
        self.personas[name] = Persona(name, persona)

    def deregister_persona(self, name):
        if name in self.personas:
            self.personas.pop(name)

    # Chatbot API
    def chatbox_ask(self, prompt: str, persona: Optional[str] = None, lang: Optional[str] = None) -> Optional[str]:
        persona = persona or self.default_persona
        if persona not in self.personas:
            LOG.error(f"unknown persona, choose one of {self.personas.keys()}")
            return None
        messages = [{"role": "user", "content": prompt}]
        return self.personas[persona].chat(messages, lang)

    def match(self, utterances: List[str], lang: Optional[str] = None, message: Optional[Message] = None) -> Optional[IntentHandlerMatch]:
        """
        Args:
            utterances (list):  list of utterances
            lang (string):      4 letter ISO language code
            message (Message):  message to use to generate reply

        Returns:
            IntentMatch if handled otherwise None.
        """
        ans = self.chatbox_ask(utterances[0], lang=lang)
        if ans:
            return IntentHandlerMatch(match_type='persona:answer',
                                      match_data={"answer": ans},
                                      skill_id="persona.openvoiceos",
                                      utterance=utterances[0])

    def handle_persona_answer(self, message):
        utt = message.data["answer"]
        self.speak(utt)


if __name__ == "__main__":
    b = PersonaService(FakeBus(),
                       config={"personas_path": "/home/miro/PycharmProjects/ovos-persona/personas"})
    print(b.personas)

    print(b.match(["what is the speed of light"]))

    # The speed of light has a value of about 300 million meters per second
    # The telephone was invented by Alexander Graham Bell
    # Stephen William Hawking (8 January 1942 – 14 March 2018) was an English theoretical physicist, cosmologist, and author who, at the time of his death, was director of research at the Centre for Theoretical Cosmology at the University of Cambridge.
    # 42
    # critical error, brain not available
