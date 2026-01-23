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
        """
        Create and initialize the PersonaService, load personas and intent matchers, and register message-bus handlers.
         
        Parameters:
            bus (Optional[MessageBusClient | FakeBus]): Message bus client used for events and IPC. If omitted, a local FakeBus is created.
            config (Optional[dict]): Persona-specific configuration. If omitted, the service reads the "intents.persona" section from global Configuration.
         
        Behavior:
            - Initializes base application and confidence-matching pipeline.
            - Loads personas from configured paths and plugin providers.
            - Loads per-language intent matcher files.
            - Registers message-bus event handlers for persona operations and utterance/speak events.
            - Initializes runtime state: `message_history` (per-session history), `active_personas` (per-session active persona), `personas`, `intent_matchers`, `blacklist`, and `_active_sessions`.
        """
        bus = bus or FakeBus()
        config = config or Configuration().get("intents", {}).get("persona", {})
        OVOSAbstractApplication.__init__(self, bus=bus, skill_id="persona.openvoiceos",
                                         resources_dir=f"{dirname(__file__)}")
        ConfidenceMatcherPipeline.__init__(self, bus=bus, config=config)
        self.message_history = {}  # per session_id
        self.active_personas = {}  # per session_id
        self.personas = {}
        self.intent_matchers = {}
        self.blacklist = self.config.get("persona_blacklist") or []
        self.load_personas(self.config.get("personas_path"))
        # is_intent flag ensures "ovos.utterance.handled" is emitted
        self.add_event('persona:query', self.handle_persona_query, is_intent=True)
        self.add_event('persona:summon', self.handle_persona_summon, is_intent=True)
        self.add_event('persona:list', self.handle_persona_list, is_intent=True)
        self.add_event('persona:check', self.handle_persona_check, is_intent=True)
        self.add_event('persona:release', self.handle_persona_release, is_intent=True)
        self.add_event("speak", self.handle_speak)
        self.add_event("recognizer_loop:utterance", self.handle_utterance)
        self.load_intent_files()
        self._active_sessions = {}

    @classmethod
    def load_resource_files(cls):
        """
        Load intent sample texts from this package's locale resources for configured languages.
        
        For each language in Configuration().get('secondary_langs') plus the primary language (Configuration().get('lang')), locate the package locale directory for that language and collect files whose names match entries in cls.INTENTS. Each matching file is read as newline-separated samples; doubled braces `{{` / `}}` in samples are collapsed to single `{` / `}`. Missing languages or intent files are skipped.
        
        Returns:
            dict: Mapping from language tag to a dict of intent name -> list of sample strings, i.e. {language: {intent_name: [sample, ...], ...}, ...}.
        """
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
        # TODO - make intent backend configurable, padatious is not a good choice...
        """
        Load and prepare intent matchers for each configured language and register persona intent samples.

        Builds a per-language IntentContainer (using a cache directory when applicable), registers intent samples sourced from locale/resource files, and trains or instantiates matchers when the configured backend requires it. Skips training for known problematic language/intent combinations and logs failures for individual intent registrations.

        Side effects:
        - Populates and updates self.intent_matchers with initialized IntentContainer instances keyed by language tag.
        - Reads intent samples via self.load_resource_files().
        - Uses the configured intent cache directory for backends that support disk caching.
        """
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
        """
        Determine the default persona name for this service.
        
        If a `default_persona` is configured, returns the best-matching loaded persona name. If no configuration is present but personas are loaded, returns the first loaded persona name. Returns `None` when no persona can be resolved.
        
        Returns:
            Optional[str]: The resolved persona name, or `None` if no personas are available.
        """
        persona = self.config.get("default_persona")
        if persona: # match config against loaded personas
            persona = self.match_persona(persona)
        elif self.personas:
            persona = list(self.personas.keys())[0]
        return persona

    def get_active_persona(self, message, include_default=True) -> Optional[str]:
        """
        Determine the active persona for the given message/session following priority rules.
        
        Checks, in order: an explicitly requested persona in message.data, a session-scoped active persona, the session's default persona (if include_default), and the configured default persona (if include_default).
        
        Parameters:
            message: The incoming message object containing session/context data.
            include_default (bool): If True, allow falling back to the session or configured default persona.
        
        Returns:
            Optional[str]: The resolved persona name if one is found, `None` otherwise.
        """
        sess = SessionManager.get(message)
        # prioritize explicitly requested persona via message.data (eg, summon intent)
        if message and message.data.get("persona"):
            persona = self.match_persona(message.data.get("persona"))
            if persona:
                return persona
        # check if a persona is active
        if sess.session_id in self.active_personas:
            return self.active_personas[sess.session_id]
        # default persona from Session
        elif sess.persona_id and include_default:
            return sess.persona_id
        # default persona from config
        elif self.default_persona and include_default:
            return self.default_persona
        return None

    def match_persona(self, persona: str):
        """
        Finds the registered persona name that best matches the given input using case-insensitive partial token-set fuzzy matching.
        
        Parameters:
            persona (str): Candidate persona name or phrase to match against registered personas.
        
        Returns:
            str or None: The matched persona name if the similarity score is at least 0.7, `None` if the input is empty or no persona meets the threshold.
        """
        if not persona:
            return None
        # TODO - make MatchStrategy configurable
        match, score = match_one(persona, list(self.personas),
                                 strategy=MatchStrategy.PARTIAL_TOKEN_SET_RATIO, 
                                 ignore_case=True)
        LOG.debug(f"Closest persona: {match} - {score}")
        return match if score >= 0.7 else None

    def load_personas(self, personas_path: Optional[str] = None):
        """
        Discover and register persona definitions from disk and from installed persona plugins into this service.
        
        Scans the provided directory for JSON files (or the XDG config path if None), creates Persona instances for each file found, and registers them under their filename or the JSON's "name" field. Skips personas present in self.blacklist. Errors while loading individual persona files are logged and do not stop processing. Unless the configuration key "ignore_plugin_personas" is true, also loads persona definitions discovered from installed plugin providers, skipping blacklisted names and any persona already loaded from disk.
        
        Parameters:
            personas_path (Optional[str]): Directory to read user-defined persona JSON files from. If None, the XDG config path for "ovos_persona" is used.
        """
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
        if self.config.get("ignore_plugin_personas", False):
            return

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
        """
        Register or update a persona under the given name using the provided configuration.
        
        Parameters:
            name (str): Identifier for the persona.
            persona (dict): Persona configuration dictionary used to construct the Persona instance.
        """
        self.personas[name] = Persona(name, persona)

    def deregister_persona(self, name):
        """
        Deregister a persona by name, removing it from the service's registry if found.
        
        Parameters:
            name (str): Exact or partial persona name to remove; the input will be resolved to a registered persona (fuzzy/case-insensitive match) before removal.
        """
        name = self.match_persona(name) or ""
        if name in self.personas:
            self.personas.pop(name)

    # Chatbot API
    def chatbox_ask(self, prompt: str,
                    persona: Optional[str] = None,
                    lang: Optional[str] = None,
                    message: Message = None,
                    stream: bool = True) -> Iterable[str]:
        """
        Ask a persona a prompt and yield its response(s), optionally as a streamed sequence.
        
        The target persona is resolved from the provided `persona` (fuzzy match) or from the message/session active persona (including the configured default). If short-term memory is enabled, recent per-session Q/A pairs from `message` are prepended to the prompt as context. Streaming delegates to the persona's streaming interface; non-streaming returns the full reply as a single yielded string.
        
        Parameters:
            prompt (str): The user prompt to send to the persona.
            persona (Optional[str]): Persona name or partial name to resolve; if omitted, the active/session/default persona is used.
            lang (Optional[str]): Language tag to use for the request; if omitted, the session language is used.
            message (Message): Optional message object used to resolve the session, language, and to gather short-term memory.
            stream (bool): If True, yield incremental/streamed response fragments; if False, yield one complete response.
        
        Returns:
            Iterable[str]: An iterator that yields response strings. Returns None (and yields nothing) if the resolved persona is not found.
        """
        persona = self.match_persona(persona) or self.get_active_persona(message, include_default=True)
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
        """
        Reconstructs recent question/answer pairs for the session associated with `message`.
        
        Scans the per-session message_history for the session id derived from `message` and returns a list of (question, answer) tuples in chronological order. Consecutive AI "speak" entries are concatenated into a single answer separated by ". ". If no history exists for the session, returns an empty list.
        
        Parameters:
            message (Message): Bus message used to obtain the session and session_id.
        
        Returns:
            list[tuple[str, str]]: Chronological list of (question, answer) pairs for the session.
        """
        sess = SessionManager.get(message)
        if sess.session_id not in self.message_history:
            return []
        messages = []  # tuple of question, answer

        q = None
        ans = None
        for m in self.message_history[sess.session_id]:
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
        High-priority intent matcher for persona-related utterances.
       
        Analyzes the first utterance (language-normalized) for persona control and query intents. It:
        - Detects a release intent when a session has an active persona and returns a 'persona:release' match.
        - Uses per-language intent matchers to identify persona intents (summon, list, active_persona, ask).
        - Applies the configured minimum intent confidence threshold before accepting a match.
        - For 'summon.intent', returns a 'persona:summon' match when a persona entity is present.
        - For 'list_personas.intent', returns a 'persona:list' match.
        - For 'active_persona.intent', returns a 'persona:check' match.
        - For 'ask.intent', requires both persona and utterance entities and verifies the persona against registered personas via match_persona; returns a 'persona:query' match when verified.
        - If an active persona exists and no explicit persona intent is accepted, delegates to the low-priority matcher to allow persona-scoped handling.
       
        Parameters:
            utterances (List[str]): Candidate user utterances; only the first entry is used for matching.
            lang (Optional[str]): Language tag to use for intent matching; will be standardized if provided.
            message (Optional[Message]): Message object providing session/context (used to detect session active persona).
       
        Returns:
            IntentHandlerMatch or None: An IntentHandlerMatch for handled persona intents (`persona:release`, `persona:summon`, `persona:list`, `persona:check`, `persona:query`) or `None` if no high-priority persona intent was matched.
        """
        lang = lang or self.lang
        lang = standardize_lang_tag(lang)
        active_persona = self.get_active_persona(message, include_default=False)
        if active_persona and self.voc_match(utterances[0], "Release", lang):
            return IntentHandlerMatch(match_type='persona:release',
                                      match_data={"persona": active_persona},
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
                    persona = self.match_persona(persona)
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
            if active_persona:
                LOG.debug(f"Persona is active: {active_persona}")
                return self.match_low(utterances, lang, message)

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Attempt medium-priority intent matching for persona-related utterances and return a corresponding IntentHandlerMatch when detected.
        
        Normalizes the language tag and checks, in order: (1) if a session has an active persona and the utterance matches a "Release" vocabulary, return a 'persona:release' match; (2) perform an adapt-like heuristic for queries that mention a known persona name and match "ask" + "opinion" or "summon" vocabularies, returning a 'persona:query' or 'persona:summon' match with extracted persona and query data. Matches use the closest supported language available and require both a resolved persona and query where applicable; misclassifications are ignored.
        
        Parameters:
            utterances (List[str]): Candidate utterances (first element is used as the primary input).
            lang (str): Requested language tag or None to use the service default.
            message (Message): The incoming message object (used to resolve session-specific active persona).
        
        Returns:
            IntentHandlerMatch or None: An IntentHandlerMatch for 'persona:release', 'persona:summon', or 'persona:query' when a medium-priority persona intent is found, otherwise None.
        """
        lang = lang or self.lang
        lang = standardize_lang_tag(lang)

        active_persona = self.get_active_persona(message, include_default=False)
        if active_persona and self.voc_match(utterances[0], "Release", lang):
            return IntentHandlerMatch(match_type='persona:release',
                                      match_data={"persona": active_persona},
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
                    persona = self.match_persona(persona)
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
        Attempt a final fallback match that routes the first utterance to an active or default persona.
          
        If a higher-priority medium match is found, it is returned. Otherwise, this method resolves the session's active persona (or the configured default when allowed) and constructs an IntentHandlerMatch of type "persona:query" containing the first utterance, language, and resolved persona. This match is intended as the last-resort handler in the matching pipeline and only produced when a persona is available (and fallback handling is enabled when necessary).
          
        Parameters:
            utterances (List[str]): Candidate utterances (first element is used for the fallback query).
            lang (Optional[str]): Language tag (e.g., "en-US") used for context resolution.
            message (Optional[Message]): Optional message object used to resolve session-specific active persona.
          
        Returns:
            Optional[IntentHandlerMatch]: An IntentHandlerMatch of type "persona:query" when a fallback persona is resolved, `None` if no persona match or fallback is applicable.
        """
        match = self.match_medium(utterances, lang, message)
        if match:
            return match

        persona = self.get_active_persona(message, include_default=False)
        if not persona and self.config.get("handle_fallback"):
            # read default persona from session/config
            persona = self.get_active_persona(message, include_default=True)
            if not persona:
                LOG.error("configured default persona is invalid, can't handle utterance")

        # always matches! use as last resort in pipeline
        if persona:
            return IntentHandlerMatch(match_type='persona:query',
                                      match_data={"utterance": utterances[0],
                                                  "lang": lang,
                                                  "persona": persona},
                                      skill_id="persona.openvoiceos",
                                      utterance=utterances[0])

    # bus events
    def handle_utterance(self, message):
        """
        Store the incoming user utterance in the per-session message history.
        
        Parameters:
            message: Bus message object containing a `data` dict with an `utterances` list.
                The first element of that list is taken as the user utterance. The session
                is resolved via SessionManager.get(message); its `session_id` is used as
                the key in `self.message_history`.
        
        Side effects:
            Appends a tuple `("user", utterance)` to `self.message_history[session_id]`.
        """
        utt = message.data.get("utterances")[0]
        sess = SessionManager.get(message)
        if sess.session_id not in self.message_history:
            self.message_history[sess.session_id] = []
        self.message_history[sess.session_id].append(("user", utt))

    def handle_speak(self, message):
        """
        Store a system/AI utterance in the session's short-term message history.
        
        Appends a tuple ("ai", utterance) to self.message_history for the session identified by the incoming bus message if that session already has a history entry. If the session has no existing history entry, no action is taken.
        
        Parameters:
            message: Bus message object containing `data["utterance"]` and session info retrievable via SessionManager.get(message).
        """
        utt = message.data.get("utterance")
        sess = SessionManager.get(message)
        if sess.session_id in self.message_history:
            self.message_history[sess.session_id].append(("ai", utt))

    def handle_persona_check(self, message: Optional[Message] = None):
        """
        Announces the currently active persona for the message's session.
        
        If a persona is active for the session resolved from `message`, speaks the
        "active_persona" dialog with the persona name; otherwise speaks the
        "no_active_persona" dialog.
        
        Parameters:
            message (Optional[Message]): Message whose session is used to determine the
                active persona. If omitted, resolves without a session-specific message.
        """
        active_persona = self.get_active_persona(message, include_default=False)
        if active_persona:
            self.speak_dialog("active_persona", {"persona": active_persona})
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
        """
        Handle a persona query message by running the utterance against the resolved active persona and speaking streamed responses.
        
        Processes the incoming message to determine session and language, resolves the target persona (including the configured default), and validates that the persona is loaded. If no personas are available or the resolved persona is unknown, speaks the appropriate dialog and may list available personas. If valid, marks the session as active and iterates the persona's chat responses from chatbox_ask, speaking each non-empty partial result and stopping early if the session is cancelled. If no answer is produced, speaks an error dialog.
        
        Parameters:
            message: MessageBus message object containing at minimum:
                - data["utterance"]: the user's utterance text to send to the persona.
                - optional data["lang"]: language code to use for the query; falls back to the session language.
        """
        if not self.personas:
            self.speak_dialog("no_personas")
            return

        sess = SessionManager.get(message)
        utt = message.data["utterance"]
        lang = message.data.get("lang") or sess.lang
        persona = self.get_active_persona(message, include_default=True)
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
        """
        Activate a persona for the current session based on the incoming message.
        
        If no personas are loaded, speaks the "no_personas" dialog. Otherwise attempts to resolve the requested persona name from message.data["persona"]; if the name does not match a loaded persona, speaks the "unknown_persona" dialog with the provided name. If a matching persona is found, marks it as the active persona for the session, logs the activation, and speaks the "activated_persona" dialog.
        
        Parameters:
            message: Bus message containing at least `data["persona"]` and session information used to scope the activation.
        """
        if not self.personas:
            self.speak_dialog("no_personas")
            return

        sess = SessionManager.get(message)
        persona = message.data["persona"]
        persona = self.match_persona(persona) or persona
        if persona not in self.personas:
            self.speak_dialog("unknown_persona", {"persona": persona})
        else:
            LOG.info(f"Persona enabled: {persona}")
            self.active_personas[sess.session_id] = persona
            self.speak_dialog("activated_persona", {"persona": persona})

    def handle_persona_release(self, message):
        # NOTE: below never happens, this intent only matches if self.active_persona
        # if for some miracle this handle is called speak dedicated dialog
        """
        Release the currently active persona for the incoming message's session and announce the action.
        
        If a persona is active for the session, announces release via dialog, clears the session's active persona, and logs the release. If no persona is active, announces that no persona is active.
        
        Parameters:
            message: The incoming message object from the message bus (provides session context).
        """
        active_persona = self.get_active_persona(message, include_default=False)
        if not active_persona:
            self.speak_dialog("no_active_persona")
            return
        sess = SessionManager.get(message)
        LOG.info(f"Releasing Persona: {active_persona}  for session: {sess.session_id}")
        self.speak_dialog("release_persona", {"persona": active_persona})
        if sess.session_id in self.active_personas:
            self.active_personas.pop(sess.session_id)

    def stop_session(self, session: Session):
        # since responses are streaming, this will exit the loop in hanle_persona_query
        """
        Stop any active streaming response loop for the given session.
        
        Marks the session as inactive so ongoing streaming handlers (if any) will exit.
        
        Parameters:
            session (Session): Session whose streaming responses should be stopped; the session's session_id is used.
        
        Returns:
            bool: `True` if a running session was active and was stopped, `False` otherwise.
        """
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
