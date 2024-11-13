import json
import os
from os.path import join, dirname
from typing import Optional, Dict, List, Union, Iterable

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.session import SessionManager
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

try:
    from ovos_plugin_manager.solvers import find_chat_solver_plugins
except ImportError:
    def find_chat_solver_plugins():
        return {}


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
        for plug_name, plug in find_chat_solver_plugins().items():
            if plug_name not in persona or plug_name in blacklist:
                plugs[plug_name] = {"enabled": False}
            else:
                plugs[plug_name] = config.get(plug_name) or {"enabled": True}
        self.solvers = QuestionSolversService(config=plugs)

    def __repr__(self):
        return f"Persona({self.name}:{list(self.solvers.loaded_modules.keys())})"

    def chat(self, messages: list = None, lang: str = None) -> str:
        return self.solvers.chat_completion(messages, lang)

    def stream(self, messages: list = None, lang: str = None) -> Iterable[str]:
        return self.solvers.stream_completion(messages, lang)


class PersonaService(PipelineStageConfidenceMatcher, OVOSAbstractApplication):

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        config = config or Configuration().get("persona", {})
        OVOSAbstractApplication.__init__(
            self, bus=bus or FakeBus(), skill_id="persona.openvoiceos",
            resources_dir=f"{dirname(__file__)}")
        PipelineStageConfidenceMatcher.__init__(self, bus, config)
        self.sessions = {}
        self.personas = {}
        self.intent_matchers = {}
        self.blacklist = self.config.get("persona_blacklist") or []
        self.load_personas(self.config.get("personas_path"))
        self.active_persona = None
        self.add_event('persona:query', self.handle_persona_query)
        self.add_event('persona:summon', self.handle_persona_summon)
        self.add_event('persona:release', self.handle_persona_release)
        self.add_event("speak", self.handle_speak)
        self.add_event("recognizer_loop:utterance", self.handle_utterance)

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
                    if f in ["ask.intent", "summon.intent"]:
                        with open(path) as intent:
                            samples = intent.read().split("\n")
                            for idx, s in enumerate(samples):
                                samples[idx] = s.replace("{{", "{").replace("}}", "}")
                            intents[lang][f] = samples
        return intents

    def load_intent_files(self):
        intent_files = self.load_resource_files()
        for lang, intent_data in intent_files.items():
            lang = standardize_lang_tag(lang)
            self.intent_matchers[lang] = IntentContainer()
            for intent_name in ["ask.intent", "summon.intent"]:
                samples = intent_data.get(intent_name)
                if samples:
                    LOG.debug(f"registering OCP intent: {intent_name}")
                    self.intent_matchers[lang].add_intent(
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
            LOG.info(f"Found persona (user defined): {name}")
            self.personas[name] = Persona(name, persona)

        # load personas provided by packages
        for name, persona in find_persona_plugins().items():
            if name in self.blacklist:
                continue
            if name in self.personas:
                LOG.info(f"Ignoring persona (provided via plugin): {name}")
                continue
            LOG.info(f"Found persona (provided via plugin): {name}")
            self.personas[name] = Persona(name, persona)

    def register_persona(self, name, persona):
        self.personas[name] = Persona(name, persona)

    def deregister_persona(self, name):
        if name in self.personas:
            self.personas.pop(name)

    # Chatbot API
    def chatbox_ask(self, prompt: str,
                    persona: Optional[str] = None,
                    lang: Optional[str] = None,
                    message: Message = None,
                    stream: bool = True) -> Iterable[str]:
        persona = persona or self.active_persona or self.default_persona
        if persona not in self.personas:
            LOG.error(f"unknown persona, choose one of {self.personas.keys()}")
            return None
        messages = []
        message = message or dig_for_message()
        if message:
            for q, a in self._build_msg_history(message):
                messages.append({"role": "user", "content": q})
                messages.append({"role": "assistant", "content": a})
        messages.append({"role": "user", "content": prompt})
        if stream:
            yield from self.personas[persona].stream(messages, lang)
        else:
            ans = self.personas[persona].chat(messages, lang)
            if ans:
                yield ans

    def _build_msg_history(self, message: Message):
        sess = SessionManager.get(message)
        if sess.session_id not in self.sessions:
            return []
        messages = []  # tuple of question, answer

        q = None
        ans = None
        for m in self.sessions[sess.session_id]:
            if m[0] == "user":
                if ans is not None and q is not None:
                    # save previous q/a pair
                    messages.append((q, ans))
                    q = None
                ans = None
                q = m[1]  # track question
            elif m[0] == "ai":
                if ans is None:
                    ans = m[1]  # track answer
                else:  # merge multi speak answers
                    ans = f"{ans}. {m[1]}"

        # save last q/a pair
        if ans is not None and q is not None:
            messages.append((q, ans))
        return messages

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
        if self.active_persona and self.voc_match(utterances[0], "Release", lang):
            return IntentHandlerMatch(match_type='persona:release',
                                      match_data={"persona": self.active_persona},
                                      skill_id="persona.openvoiceos",
                                      utterance=utterances[0])

        match = self.intent_matchers[lang].calc_intent(utterances[0].lower())

        if match["name"]:
            LOG.info(f"Persona intent exact match: {match}")
            persona = match["entities"].pop("persona")
            if match["name"] == "summon":
                return IntentHandlerMatch(match_type='persona:summon',
                                          match_data={"persona": persona},
                                          skill_id="persona.openvoiceos",
                                          utterance=utterances[0])
            elif match["name"] == "ask":
                utterance = match["entities"].pop("query")
                return IntentHandlerMatch(match_type='persona:query',
                                          match_data={"utterance": utterance,
                                                      "lang": lang,
                                                      "persona": persona},
                                          skill_id="persona.openvoiceos",
                                          utterance=utterances[0])

        # override regular intent parsing, handle utterance until persona is released
        if self.active_persona:
            LOG.debug(f"Persona is active: {self.active_persona}")
            return self.match_low(utterances, lang, message)

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
        # always matches! use as last resort in pipeline
        return IntentHandlerMatch(match_type='persona:query',
                                  match_data={"utterance": utterances[0],
                                              "lang": lang,
                                              "persona": self.active_persona or self.default_persona},
                                  skill_id="persona.openvoiceos",
                                  utterance=utterances[0])

    # bus events
    def handle_utterance(self, message):
        utt = message.data.get("utterances")[0]
        sess = SessionManager.get(message)
        if sess.session_id not in self.sessions:
            self.sessions[sess.session_id] = []
        self.sessions[sess.session_id].append(("user", utt))

    def handle_speak(self, message):
        utt = message.data.get("utterance")
        sess = SessionManager.get(message)
        if sess.session_id in self.sessions:
            self.sessions[sess.session_id].append(("ai", utt))

    def handle_persona_query(self, message):
        utt = message.data["utterance"]
        lang = message.data["lang"]
        persona = message.data["persona"]

        if persona not in self.personas:
            self.speak_dialog("unknown_persona", {"persona": persona})
            return

        handled = False
        for ans in self.chatbox_ask(utt, lang=lang, persona=persona):
            self.speak(ans)
            handled = True
        if not handled:
            self.speak_dialog("persona_error")

    def handle_persona_summon(self, message):
        persona = message.data["persona"]
        if persona not in self.personas:
            self.speak_dialog("unknown_persona", {"persona": persona})
        else:
            self.active_persona = persona
            LOG.info(f"Summoned Persona: {self.active_persona}")

    def handle_persona_release(self, message):
        LOG.info(f"Releasing Persona: {self.active_persona}")
        self.speak_dialog("release_persona", {"persona": self.active_persona})
        self.active_persona = None


if __name__ == "__main__":
    b = PersonaService(FakeBus())
    print(b.personas)

    print(b.match_low(["what is the speed of light"]))
    for ans in b.chatbox_ask("what is the speed of light"):
        print(ans)
    # The speed of light has a value of about 300 million meters per second
    # The telephone was invented by Alexander Graham Bell
    # Stephen William Hawking (8 January 1942 – 14 March 2018) was an English theoretical physicist, cosmologist, and author who, at the time of his death, was director of research at the Centre for Theoretical Cosmology at the University of Cambridge.
    # 42
    # critical error, brain not available
