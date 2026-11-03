"""`QuestionSolversService.modules` orders handlers without reading a
deprecated attribute.

`priority` is opt-in: neither `ChatEngine` nor `QuestionSolver` declares one,
so a service built with no `sort_order` must still be able to list its
handlers.
"""
from unittest.mock import patch

from ovos_plugin_manager.templates.agents import (AgentMessage, ChatEngine,
                                                  MessageRole)

from ovos_persona.solvers import QuestionSolversService


class _Handler(ChatEngine):
    """A handler that declares no `priority`, which is the ordinary case."""

    def continue_chat(self, messages, session_id="default", lang=None,
                      units=None, tools=None):
        return AgentMessage(MessageRole.ASSISTANT, "answer")


class _Prioritised(_Handler):
    """A handler that still declares the deprecated attribute."""

    priority = 1


def _service(modules, sort_order=None):
    """A service holding `modules`, an ordered list of (name, handler)."""
    with patch("ovos_persona.solvers.get_utterance_handler_plugins",
               return_value={}):
        svc = QuestionSolversService(config={})
    svc.loaded_modules = {name: handler for name, handler in modules}
    svc.sort_order = sort_order or []
    return svc


def test_a_handler_without_priority_lists_without_a_sort_order():
    """The defect: reading `k.priority` raised
    `AttributeError: 'X' object has no attribute 'priority'` and took the whole
    chain down, so a service built directly could not be used at all."""
    svc = _service([("plain", _Handler({}))])
    assert svc.modules == [svc.loaded_modules["plain"]]


def test_the_chain_answers_without_a_sort_order():
    """`modules` is read by every completion call, so the failure above reached
    a caller that never touched the property itself."""
    svc = _service([("plain", _Handler({}))])
    reply = svc.chat_completion([AgentMessage(MessageRole.USER, "anything")])
    assert reply == "answer"


def test_load_order_is_kept_between_handlers_without_priority():
    """Handlers that share a sort key keep the order they were loaded in,
    because the sort is stable. Without that, the order of a chain built with
    no sort_order would depend on nothing a caller can see."""
    first, second, third = _Handler({}), _Handler({}), _Handler({})
    svc = _service([("a", first), ("b", second), ("c", third)])
    assert svc.modules == [first, second, third]


def test_a_declared_priority_still_comes_first():
    """A handler that still carries the deprecated attribute keeps its place,
    so this change moves no existing chain."""
    plain, prioritised = _Handler({}), _Prioritised({})
    svc = _service([("plain", plain), ("prioritised", prioritised)])
    assert svc.modules == [prioritised, plain]


def test_sort_order_still_decides_when_it_is_given():
    """The path a Persona uses: `sort_order` is the persona's `handlers` list
    and it wins over any attribute."""
    plain, prioritised = _Handler({}), _Prioritised({})
    svc = _service([("plain", plain), ("prioritised", prioritised)],
                   sort_order=["plain", "prioritised"])
    assert svc.modules == [plain, prioritised]
