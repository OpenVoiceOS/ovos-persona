from typing import Optional, List, Iterable, Union, Dict, Type

from ovos_utils import flatten_list
from ovos_config import Configuration
from ovos_plugin_manager.solvers import find_chat_solver_plugins, find_question_solver_plugins
from ovos_plugin_manager.templates.solvers import ChatMessageSolver, QuestionSolver
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_plugin_manager.templates.agents import MessageRole, AgentMessage, ChatEngine, MultimodalChatEngine,   RetrievalEngine, DocumentIndexerEngine,  QAIndexerEngine


UtteranceHandlerClass = Union[Type[ChatMessageSolver],
                         Type[QuestionSolver],
                         Type[ChatEngine],
                         Type[MultimodalChatEngine],
                         Type[RetrievalEngine],
                         Type[DocumentIndexerEngine],
                         Type[QAIndexerEngine]]


def get_utterance_handler_plugins() -> Dict[str, UtteranceHandlerClass]:
    # TODO - load new AgentEngine plugins
    return {
        **find_question_solver_plugins(),
        **find_chat_solver_plugins()
    }


class QuestionSolversService:
    def __init__(self, bus=None, config=None, sort_order=None):
        self.config_core = Configuration()
        self.loaded_modules = {}
        self.sort_order = sort_order or []
        self.bus = bus or FakeBus()
        self.config = config or {}
        self.load_plugins()

    def load_plugins(self):
        for plug_name, plug_class in get_utterance_handler_plugins().items():
            config = self.config.get(plug_name) or {}
            if not config.get("enabled", True):
                continue
            LOG.debug(f"loading plugin with cfg: {config}")
            self.loaded_modules[plug_name] = plug_class(config=config)
            LOG.info(f"loaded {plug_class.__name__} plugin: {plug_name}")

        plugs = [p for p, c in self.config.items() if c.get("enabled", True)]
        for p in plugs:
            if p not in self.loaded_modules:
                raise ImportError(f"'{p}' not installed")

    @property
    def modules(self):
        if self.sort_order:
            return [self.loaded_modules[m] for m in self.sort_order]
        return sorted(self.loaded_modules.values(),
                      key=lambda k: k.priority)

    def shutdown(self):
        for module in self.modules:
            try:
                module.shutdown()
            except:
                pass

    def chat_completion(self, messages: List[AgentMessage],
                        session_id: str = "default",
                        lang: Optional[str] = None,
                        units: Optional[str] = None) -> Optional[str]:
        for module in self.modules:
            try:
                ans = None
                if isinstance(module, (ChatEngine, MultimodalChatEngine)):
                    response = module.continue_chat(messages,
                                                    session_id=session_id,
                                                    lang=lang, units=units)
                    ans = response.content
                elif isinstance(module, (RetrievalEngine, DocumentIndexerEngine, QAIndexerEngine)):
                    document, conf = module.query(messages[-1].content,
                                                  lang=lang, k=1)[0]
                    ans = document
                elif isinstance(module, ChatMessageSolver):
                    ans = module.get_chat_completion(messages=messages, lang=lang, units=units)
                elif isinstance(module, QuestionSolver):
                    LOG.debug(f"{module} does not supported chat history!")
                    query = messages[-1].content
                    ans = module.spoken_answer(query, lang=lang, units=units)
                if ans:
                    return ans
            except Exception as e:
                LOG.error(e)
        return None

    def stream_completion(self, messages: List[AgentMessage],
                          session_id: str = "default",
                          lang: Optional[str] = None,
                          units: Optional[str] = None) -> Iterable[str]:
        answered = False
        for module in self.modules:
            try:
                if isinstance(module, (ChatEngine, MultimodalChatEngine)):
                    for response in module.stream_chat(messages,
                                                    session_id=session_id,
                                                    lang=lang, units=units):

                        answered = True
                        yield response.content
                elif isinstance(module, (RetrievalEngine, DocumentIndexerEngine, QAIndexerEngine)):
                    document, conf = module.query(messages[-1].content,
                                                  lang=lang, k=1)[0]
                    answered = True
                    yield document
                elif isinstance(module, ChatMessageSolver):
                    for ans in module.stream_chat_utterances(messages=messages, lang=lang, units=units):
                        answered = True
                        yield ans
                elif isinstance(module, QuestionSolver):
                    LOG.debug(f"{module} does not supported chat history!")
                    query = messages[-1].content
                    for ans in module.stream_utterances(query, lang=lang, units=units):
                        answered = True
                        yield ans

            except Exception as e:
                LOG.error(e)
            if answered:
                break
