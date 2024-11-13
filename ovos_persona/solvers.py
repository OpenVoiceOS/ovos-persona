from typing import Optional

from ovos_config import Configuration
from ovos_plugin_manager.solvers import find_question_solver_plugins
from ovos_utils.log import LOG
from ovos_utils.messagebus import FakeBus


class QuestionSolversService:
    def __init__(self, bus=None, config=None):
        self.config_core = Configuration()
        self.loaded_modules = {}
        self.bus = bus or FakeBus()
        self.config = config or {}
        self.load_plugins()

    def load_plugins(self):
        for plug_name, plug in find_question_solver_plugins().items():
            config = self.config.get(plug_name) or {}
            if not config.get("enabled", True):
                continue
            try:
                LOG.debug(f"loading plugin with cfg: {config}")
                self.loaded_modules[plug_name] = plug(config=config)
                LOG.info(f"loaded question solver plugin: {plug_name}")
            except Exception as e:
                LOG.exception(f"Failed to load question solver plugin: {plug_name}")

    @property
    def modules(self):
        return sorted(self.loaded_modules.values(),
                      key=lambda k: k.priority)

    def shutdown(self):
        for module in self.modules:
            try:
                module.shutdown()
            except:
                pass

    def spoken_answer(self, query: str,
                      lang: Optional[str] = None,
                      units: Optional[str] = None) -> Optional[str]:
        """
        Obtain the spoken answer for a given query.

        Args:
            query (str): The query text.
            lang (Optional[str]): Optional language code. Defaults to None.
            units (Optional[str]): Optional units for the query. Defaults to None.

        Returns:
            str: The spoken answer as a text response.
        """
        for module in self.modules:
            try:
                ans = module.spoken_answer(query, lang=lang)
                if ans:
                    return ans
            except Exception as e:
                LOG.error(e)
                pass
