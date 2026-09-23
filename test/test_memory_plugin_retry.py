"""A memory plugin installed after the persona loaded is picked up later.

On a runtime whose skill installer finishes after the pipeline has loaded,
``load_memory_plugin`` returns None at startup and the persona used to run
without memory until the next restart -- no history, and anything the memory
plugin injects (retrieved knowledge, for one) silently missing.
"""
from unittest.mock import patch

from ovos_bus_client import Session

from ovos_persona import Persona


class _DummyHandler:
    def __init__(self, config=None):
        self.config = config or {}

    def shutdown(self):
        pass


class _Memory:
    def __init__(self, config=None):
        self.config = config or {}

    def build_conversation_context(self, utterance, session_id):
        return [("remembered", utterance, self.config.get("depth"))]


def _persona(load):
    with patch("ovos_persona.solvers.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.load_memory_plugin", side_effect=load):
        return Persona(name="test", config={"handlers": ["dummy"],
                                            "memory_module": "late-memory",
                                            "late-memory": {"depth": 3}})


def test_a_memory_plugin_installed_later_is_used_on_a_later_question():
    installed = {"yes": False}
    load = lambda name: _Memory if installed["yes"] else None  # noqa: E731
    persona = _persona(load)
    assert persona.memory is None

    with patch("ovos_persona.load_memory_plugin", side_effect=load):
        # still missing: no memory, the question alone
        assert len(persona.get_messages("hi", Session())) == 1
        installed["yes"] = True
        persona._memory_retry_at = 0.0  # the rate limit is tested below
        assert persona.get_messages("hi", Session()) == [("remembered", "hi", 3)]
    # its own config block, and no further lookups once loaded
    assert persona.memory.config == {"depth": 3}
    assert persona._memory_plugin is None


def test_a_missing_memory_plugin_is_looked_up_at_most_once_per_interval():
    calls = []
    persona = _persona(lambda name: calls.append(name))
    calls.clear()
    with patch("ovos_persona.load_memory_plugin", side_effect=lambda name: calls.append(name)):
        for _ in range(5):
            persona.get_messages("hi", Session())
    assert calls == ["late-memory"]


def test_no_memory_configured_means_no_lookups():
    calls = []
    with patch("ovos_persona.solvers.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.load_memory_plugin", side_effect=lambda n: calls.append(n)):
        persona = Persona(name="test", config={"handlers": ["dummy"], "memory_module": None})
        persona.get_messages("hi", Session())
    assert calls == []
