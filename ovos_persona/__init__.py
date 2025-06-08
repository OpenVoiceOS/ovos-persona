import json
import os
from os.path import join, dirname, expanduser
from typing import Optional, Dict, List, Union, Iterable

from langcodes import closest_match
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_config_save_path
from ovos_config.meta import get_xdg_base
from ovos_persona.solvers import QuestionSolversService

from ovos_bus_client import Session
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.session import SessionManager
from ovos_plugin_manager.persona import find_persona_plugins
from ovos_plugin_manager.solvers import find_question_solver_plugins
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.fakebus import FakeBus
from ovos_utils.lang import standardize_lang_tag, get_language_dir
from ovos_utils.list_utils import flatten_list
from ovos_utils.log import LOG
from ovos_utils.parse import match_one, MatchStrategy
from ovos_utils.xdg_utils import xdg_data_home
from ovos_workshop.app import OVOSAbstractApplication

try:
    from ovos_plugin_manager.solvers import find_chat_solver_plugins
except ImportError:
    def find_chat_solver_plugins():
        return {}
try:
    from ovos_padatious import IntentContainer
    IS_PADATIOUS = True
except ImportError:
    from padacioso import IntentContainer
    IS_PADATIOUS = False
    LOG.warning("'padatious' not installed, using 'padacioso' for Persona intents")


class Persona:
    def __init__(self, name, config, blacklist=None):
        blacklist = blacklist or []
        self.name = name
        self.config = config
        solver_order = config.get("solvers") or ["ovos-solver-failure-plugin"]
        plugs = {p: {"enabled": True} for p in solver_order}
        for plug_name, plug in find_question_solver_plugins().items():
            if plug_name not in solver_order or plug_name in blacklist:
                plugs[plug_name] = {"enabled": False}
            else:
                plugs[plug_name] = config.get(plug_name) or {"enabled": True}
        for plug_name, plug in find_chat_solver_plugins().items():
            if plug_name not in solver_order or plug_name in blacklist:
                plugs[plug_name] = {"enabled": False}
            else:
                plugs[plug_name] = config.get(plug_name) or {"enabled": True}
        self.solvers = QuestionSolversService(config=plugs, sort_order=solver_order)

    def __repr__(self):
        return f"Persona({self.name}:{list(self.solvers.loaded_modules.keys())})"

    def chat(self, messages: List[Dict[str, str]],
             lang: Optional[str] = None,
             units: Optional[str] = None) -> str:
        return self.solvers.chat_completion(messages, lang, units)

    def stream(self, messages: List[Dict[str, str]],
               lang: Optional[str] = None,
               units: Optional[str] = None) -> Iterable[str]:
        return self.solvers.stream_completion(messages, lang, units)


class PersonaService(ConfidenceMatcherPipeline, OVOSAbstractApplication):
    INTENTS = ["ask.intent", "summon.intent", "list_personas.intent", "active_persona.intent"]

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        bus = bus or FakeBus()
        config = config or Configuration().get("intents", {}).get("persona", {})
        OVOSAbstractApplication.__init__(self, bus=bus, skill_id="persona.openvoiceos",
                                         resources_dir=f"{dirname(__file__)}")
        ConfidenceMatcherPipeline.__init__(self, bus=bus, config=config)
        self.sessions = {}
        self.personas = {}
        self.intent_matchers = {}
        self.blacklist = self.config.get("persona_blacklist") or []
        self.load_personas(self.config.get("personas_path"))
        self.active_persona = None
        self.add_event('persona:query', self.handle_persona_query)
        self.add_event('persona:summon', self.handle_persona_summon)
        self.add_event('persona:list', self.handle_persona_list)
        self.add_event('persona:check', self.handle_persona_check)
        self.add_event('persona:release', self.handle_persona_release)
        self.add_event("speak", self.handle_speak)
        self.add_event("recognizer_loop:utterance", self.handle_utterance)
        self.load_intent_files()
        self._active_sessions = {}

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
                    if f in cls.INTENTS:
                        with open(path) as intent:
                            samples = intent.read().split("\n")
                            for idx, s in enumerate(samples):
                                samples[idx] = s.replace("{{", "{").replace("}}", "}")
                            intents[lang][f] = samples
        return intents

    def load_intent_files(self):
        intent_cache = expanduser(self.config.get('intent_cache') or
                                  f"{xdg_data_home()}/{get_xdg_base()}/intent_cache")
        intent_files = self.load_resource_files()
        for lang, intent_data in intent_files.items():
            lang = standardize_lang_tag(lang)
            self.intent_matchers[lang] = IntentContainer(cache_dir=f"{intent_cache}/{lang}") \
                if IS_PADATIOUS else IntentContainer()
            for intent_name in self.INTENTS:
                if lang in ["ca-ES", "gl-ES"] and intent_name in ["summon.intent", "ask.intent"]:
                    # TODO - training hangs due to too many samples
                    #  skip padatious, use keyword matching for these languages for now
                    continue
                samples = intent_data.get(intent_name) or []
                samples = flatten_list([expand_template(s) for s in samples])
                if samples:
                    LOG.debug(f"registering Persona intent: {intent_name}")
                    try:
                        self.intent_matchers[lang].add_intent(intent_name, samples)
                    except:
                        LOG.error(f"Failed to train persona intent ({lang}): {intent_name}")

            if IS_PADATIOUS:
                self.intent_matchers[lang].instantiate_from_disk()
                self.intent_matchers[lang].train()

    @property
    def default_persona(self) -> Optional[str]:
        persona = self.config.get("default_persona")
        if persona: # match config against loaded personas
            persona = self.get_persona(persona)
        elif self.personas:
            persona = list(self.personas.keys())[0]
        return persona

    def get_persona(self, persona: str):
        """
        Finds the closest matching persona name to the given input using case-insensitive partial token set matching.
        
        If no input is provided, returns the currently active persona or the default persona. Returns the matched persona name if the similarity score is at least 0.7; otherwise, returns None.
        """
        if not persona:
            return self.active_persona or self.default_persona
        # TODO - make MatchStrategy configurable
        match, score = match_one(persona, list(self.personas),
                                 strategy=MatchStrategy.PARTIAL_TOKEN_SET_RATIO, 
                                 ignore_case=True)
        LOG.debug(f"Closest persona: {match} - {score}")
        return match if score >= 0.7 else None

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
            name = persona.get("name", name)
            LOG.info(f"Found persona (user defined): {name}")
            try:
                self.personas[name] = Persona(name, persona)
            except Exception as e:
                LOG.error(f"Failed to load '{name}': {e}")

        # load personas provided by packages
        for name, persona in find_persona_plugins().items():
            if name in self.blacklist:
                continue
            if name in self.personas:
                LOG.info(f"Ignoring persona (provided via plugin): {name}")
                continue
            LOG.info(f"Found persona (provided via plugin): {name}")
            try:
                self.personas[name] = Persona(name, persona)
            except Exception as e:
                LOG.error(f"Failed to load '{name}': {e}")

    def register_persona(self, name, persona):
        self.personas[name] = Persona(name, persona)

    def deregister_persona(self, name):
        name = self.get_persona(name) or ""
        if name in self.personas:
            self.personas.pop(name)

    # Chatbot API
    def chatbox_ask(self, prompt: str,
                    persona: Optional[str] = None,
                    lang: Optional[str] = None,
                    message: Message = None,
                    stream: bool = True) -> Iterable[str]:
        persona = self.get_persona(persona) or self.active_persona or self.default_persona
        if persona not in self.personas:
            LOG.error(f"unknown persona, choose one of {self.personas.keys()}")
            return None
        messages = []
        # TODO - history per persona , not only per session
        # dont let context leak between personas
        message = message or dig_for_message()
        if message and self.config.get("short-term-memory", True):
            for q, a in self._build_msg_history(message):
                messages.append({"role": "user", "content": q})
                messages.append({"role": "assistant", "content": a})
        messages.append({"role": "user", "content": prompt})
        sess = SessionManager.get(message)
        lang = lang or sess.lang
        if stream:
            yield from self.personas[persona].stream(messages, lang, sess.system_unit)
        else:
            ans = self.personas[persona].chat(messages, lang, sess.system_unit)
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
        lang = lang or self.lang
        lang = standardize_lang_tag(lang)

        if self.active_persona and self.voc_match(utterances[0], "Release", lang):
            return IntentHandlerMatch(match_type='persona:release',
                                      match_data={"persona": self.active_persona},
                                      skill_id="persona.openvoiceos",
                                      utterance=utterances[0])

        supported_langs = list(self.intent_matchers.keys())
        closest_lang, distance = closest_match(lang, supported_langs, max_distance=10)
        if closest_lang != "und":
            match = None
            match = match or self.intent_matchers[closest_lang].calc_intent(utterances[0].lower()) or {}
            name = match.name if hasattr(match, "name") else match.get("name")
            conf = match.conf if hasattr(match, "conf") else match.get("conf", 0)
            if conf < self.config.get("min_intent_confidence", 0.6):
                LOG.debug(f"Ignoring low confidence persona intent: {match}")
                name = None
            if name:
                LOG.info(f"Persona intent exact match: {match}")
                entities = match.matches if hasattr(match, "matches") else match.get("entities", {})
                persona = entities.get("persona")
                query = entities.get("utterance")
                if name == "summon.intent" and persona: # if persona name not in match, its a misclassification
                    return IntentHandlerMatch(match_type='persona:summon',
                                              match_data={"persona": persona},
                                              skill_id="persona.openvoiceos",
                                              utterance=utterances[0])
                elif name == "list_personas.intent":
                    return IntentHandlerMatch(match_type='persona:list',
                                              match_data={"lang": lang},
                                              skill_id="persona.openvoiceos",
                                              utterance=utterances[0])
                elif name == "active_persona.intent":
                    return IntentHandlerMatch(match_type='persona:check',
                                              match_data={"lang": lang},
                                              skill_id="persona.openvoiceos",
                                              utterance=utterances[0])
                elif name == "ask.intent" and persona and query:
                    # if persona name or query not in match, its a misclassification
                    persona = self.get_persona(persona)
                    if persona: # name in intent must match a registered persona
                        return IntentHandlerMatch(match_type='persona:query',
                                                  match_data={"utterance": query,
                                                              "lang": lang,
                                                              "persona": persona},
                                                  skill_id="persona.openvoiceos",
                                                  utterance=utterances[0])
                    else:
                        LOG.debug("Discarding ask.intent, requested persona doesn't match any registered persona")
                        # TODO - consider matching and reprompting user

            # override regular intent parsing, handle utterance until persona is released
            if self.active_persona:
                LOG.debug(f"Persona is active: {self.active_persona}")
                return self.match_low(utterances, lang, message)

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        lang = lang or self.lang
        lang = standardize_lang_tag(lang)

        if self.active_persona and self.voc_match(utterances[0], "Release", lang):
            return IntentHandlerMatch(match_type='persona:release',
                                      match_data={"persona": self.active_persona},
                                      skill_id="persona.openvoiceos",
                                      utterance=utterances[0])

        supported_langs = list(self.intent_matchers.keys())
        closest_lang, distance = closest_match(lang, supported_langs, max_distance=10)
        if closest_lang != "und":
            match = {}
            query = utterances[0].lower()

            # adapt-like matching for querying a persona
            if any(name.lower() in query for name in self.personas):
                if (self.voc_match(query, "ask", lang=closest_lang) and
                        self.voc_match(query, "opinion", lang=closest_lang)):
                    for name in self.personas:
                        if name.lower() in query:
                            query = self.remove_voc(query, "ask", lang=closest_lang)
                            query = self.remove_voc(query, "opinion", lang=closest_lang)
                            query = self.remove_voc(query, "persona", lang=closest_lang)
                            match = {"name": "ask.intent",
                                     "conf": 0.85,
                                     "entities": {"persona": name, "query": query}}
                            break

                elif self.voc_match(query, "summon", lang=closest_lang):
                    for name in self.personas:
                        if name.lower() in query:
                            query = self.remove_voc(query, "summon", lang=closest_lang)
                            query = self.remove_voc(query, "persona", lang=closest_lang)
                            match = {"name": "summon.intent",
                                     "conf": 0.85,
                                     "entities": {"persona": name, "query": query}}
                            break

            name =  match.get("name")

            if name:
                LOG.info(f"Persona intent exact match: {match}")
                entities = match.get("entities", {})
                persona = entities.get("persona")
                query = entities.get("query")
                if name == "summon.intent" and persona:  # if persona name not in match, its a misclassification
                    return IntentHandlerMatch(match_type='persona:summon',
                                              match_data={"persona": persona},
                                              skill_id="persona.openvoiceos",
                                              utterance=utterances[0])
                elif name == "ask.intent" and persona:  # if persona name not in match, its a misclassification
                    persona = self.get_persona(persona)
                    if persona and query:  # else its a misclassification
                        utterance = match["entities"].pop("query")
                        return IntentHandlerMatch(match_type='persona:query',
                                                  match_data={"utterance": utterance,
                                                              "lang": lang,
                                                              "persona": persona},
                                                  skill_id="persona.openvoiceos",
                                                  utterance=utterances[0])

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
        match = self.match_medium(utterances, lang, message)
        if match:
            return match

        persona = self.active_persona
        if self.config.get("handle_fallback"):
            # read default persona from config
            persona = persona or self.default_persona
            if not persona:
                LOG.error("configured default persona is invalid, can't handle utterance")
        # always matches! use as last resort in pipeline
        if persona:
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

    def handle_persona_check(self, message: Optional[Message] = None):
        if self.active_persona:
            self.speak_dialog("active_persona", {"persona": self.active_persona})
        else:
            self.speak_dialog("no_active_persona")

    def handle_persona_list(self, message: Optional[Message] = None):
        if not self.personas:
            self.speak_dialog("no_personas")
            return

        self.speak_dialog("list_personas")
        for persona in self.personas:
            self.speak(persona)

    def handle_persona_query(self, message):
        if not self.personas:
            self.speak_dialog("no_personas")
            return

        sess = SessionManager.get(message)
        utt = message.data["utterance"]
        lang = message.data.get("lang") or sess.lang
        persona = message.data.get("persona", self.active_persona or self.default_persona)
        persona = self.get_persona(persona) or persona
        if persona not in self.personas:
            self.speak_dialog("unknown_persona", {"persona": persona})
            self.handle_persona_list()
            return

        LOG.debug(f"Persona query ({lang}): {persona} - \"{utt}\"")
        handled = False

        self._active_sessions[sess.session_id] = True
        for ans in self.chatbox_ask(utt, lang=lang,
                                    persona=persona,
                                    message=message):
            if not self._active_sessions[sess.session_id]: # stopped
                LOG.debug(f"Persona stopped: {persona}")
                return
            if ans:  # might be None
                self.speak(ans)
                handled = True
        if not handled:
            self.speak_dialog("persona_error", {"persona": persona})
        self._active_sessions[sess.session_id] = False

    def handle_persona_summon(self, message):
        if not self.personas:
            self.speak_dialog("no_personas")
            return

        persona = message.data["persona"]
        persona = self.get_persona(persona) or persona
        if persona not in self.personas:
            self.speak_dialog("unknown_persona", {"persona": persona})
        else:
            LOG.info(f"Persona enabled: {persona}")
            self.active_persona = persona
            self.speak_dialog("activated_persona", {"persona": persona})

    def handle_persona_release(self, message):
        # NOTE: below never happens, this intent only matches if self.active_persona
        # if for some miracle this handle is called speak dedicated dialog
        if not self.active_persona:
            self.speak_dialog("no_active_persona")
            return

        LOG.info(f"Releasing Persona: {self.active_persona}")
        self.speak_dialog("release_persona", {"persona": self.active_persona})
        self.active_persona = None

    def stop_session(self, session: Session):
        if self._active_sessions.get(session.session_id):
            self._active_sessions[session.session_id] = False
            return True
        return False


if __name__ == "__main__":
    LOG.set_level("DEBUG")
    b = PersonaService(FakeBus(),
                       config={
                           "default_persona": "ChatBot",
                           "personas_path": "/home/miro/PycharmProjects/HiveMind-rpi-hub/overlays/home/ovos/.config/ovos_persona"})
    print("Personas:", b.personas)

    print(b.match_high(["enable remote llama"]))

#    b.handle_persona_query(Message("", {"utterance": "tell me about yourself"}))
    for ans in b.chatbox_ask("what is the speed of light"):
        print(ans)
    # The speed of light has a value of about 300 million meters per second
    # The telephone was invented by Alexander Graham Bell
    # Stephen William Hawking (8 January 1942 – 14 March 2018) was an English theoretical physicist, cosmologist, and author who, at the time of his death, was director of research at the Centre for Theoretical Cosmology at the University of Cambridge.
    # 42
    # critical error, brain not available
