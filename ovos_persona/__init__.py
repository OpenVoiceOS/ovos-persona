import json
import os
from os.path import join, dirname
from typing import Optional, Dict, List, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_config_save_path
from ovos_plugin_manager.persona import find_persona_plugins
from ovos_plugin_manager.solvers import find_question_solver_plugins
from ovos_plugin_manager.templates.pipeline import PipelineStageConfidenceMatcher, IntentHandlerMatch
from ovos_utils.fakebus import FakeBus
from ovos_utils.lang import standardize_lang_tag, get_language_dir
from ovos_utils.log import LOG
from ovos_workshop.app import OVOSAbstractApplication
from padacioso import IntentContainer

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


class PersonaService(PipelineStageConfidenceMatcher, OVOSAbstractApplication):
    intents = ["ask.intent", "summon.intent"]
    intent_matchers = {}

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        config = config or Configuration().get("persona", {})
        OVOSAbstractApplication.__init__(
            self, bus=bus or FakeBus(), skill_id="persona.openvoiceos",
            resources_dir=f"{dirname(__file__)}")
        PipelineStageConfidenceMatcher.__init__(self, bus, config)
        self.personas = {}
        self.blacklist = self.config.get("persona_blacklist") or []
        self.load_personas(self.config.get("personas_path"))
        self.active_persona = None
        self.add_event('persona:answer', self.handle_persona_answer)
        self.add_event('persona:summon', self.handle_persona_summon)
        self.add_event('persona:release', self.handle_persona_release)

    @classmethod
    def load_resource_files(cls):
        intents = {}
        langs = Configuration().get('secondary_langs', []) + [Configuration().get('lang', "en-US")]
        langs = set([standardize_lang_tag(l) for l in langs])
        for lang in langs:
            intents[lang] = {}
            locale_folder = get_language_dir(join(dirname(__file__), "locale"), lang)
            if locale_folder is not None:
                for f in os.listdir(locale_folder):
                    path = join(locale_folder, f)
                    if f in cls.intents:
                        with open(path) as intent:
                            samples = intent.read().split("\n")
                            for idx, s in enumerate(samples):
                                samples[idx] = s.replace("{{", "{").replace("}}", "}")
                            intents[lang][f] = samples
        return intents

    @classmethod
    def load_intent_files(cls):
        intent_files = cls.load_resource_files()

        for lang, intent_data in intent_files.items():
            lang = standardize_lang_tag(lang)
            cls.intent_matchers[lang] = IntentContainer()
            for intent_name in cls.intents:
                samples = intent_data.get(intent_name)
                if samples:
                    LOG.debug(f"registering OCP intent: {intent_name}")
                    cls.intent_matchers[lang].add_intent(
                        intent_name.replace(".intent", ""), samples)

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
        persona = persona or self.active_persona or self.default_persona
        if persona not in self.personas:
            LOG.error(f"unknown persona, choose one of {self.personas.keys()}")
            return None
        messages = [{"role": "user", "content": prompt}]
        return self.personas[persona].chat(messages, lang)

    # Abstract methods
    def match_high(self, utterances: List[str], lang: Optional[str] = None,
                   message: Optional[Message] = None) -> Optional[IntentHandlerMatch]:
        """
        Recommended before common query

        Args:
            utterances (list):  list of utterances
            lang (string):      4 letter ISO language code
            message (Message):  message to use to generate reply

        Returns:
            IntentMatch if handled otherwise None.
        """
        match = self.intent_matchers[lang].calc_intent(utterances[0].lower())

        if match["name"]:
            LOG.info(f"Persona exact match: {match}")
            persona = match["entities"].pop("persona")
            if match["name"] == "summon":
                return IntentHandlerMatch(match_type='persona:summon',
                                          match_data={"persona": persona},
                                          skill_id="persona.openvoiceos",
                                          utterance=utterances[0])
            elif match["name"] == "ask":
                utterance = match["entities"].pop("query")
                ans = self.chatbox_ask(utterance,
                                       lang=lang,
                                       persona=persona)
                if ans:
                    return IntentHandlerMatch(match_type='persona:answer',
                                              match_data={"answer": ans,
                                                          "persona": persona},
                                              skill_id="persona.openvoiceos",
                                              utterance=utterances[0])

        if self.active_persona and self.voc_match(utterances[0], "Release", lang):
            return IntentHandlerMatch(match_type='persona:release',
                                      match_data={"persona": self.active_persona},
                                      skill_id="persona.openvoiceos",
                                      utterance=utterances[0])

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> None:
        return self.match_high(utterances, lang, message)

    def match_low(self, utterances: List[str], lang: Optional[str] = None,
                  message: Optional[Message] = None) -> Optional[IntentHandlerMatch]:
        """
        Recommended before fallback low

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

    def handle_persona_summon(self, message):
        persona = message.data["persona"]
        if persona not in self.personas:
            self.speak_dialog("unknown_persona")
        else:
            self.active_persona = persona

    def handle_persona_release(self, message):
        self.active_persona = None


if __name__ == "__main__":
    b = PersonaService(FakeBus(),
                       config={"personas_path": "/home/miro/PycharmProjects/ovos-persona/personas"})
    print(b.personas)

    print(b.match_low(["what is the speed of light"]))

    # The speed of light has a value of about 300 million meters per second
    # The telephone was invented by Alexander Graham Bell
    # Stephen William Hawking (8 January 1942 – 14 March 2018) was an English theoretical physicist, cosmologist, and author who, at the time of his death, was director of research at the Centre for Theoretical Cosmology at the University of Cambridge.
    # 42
    # critical error, brain not available
