"""Regression tests for Persona.chat / Persona.stream argument passthrough.

Persona.chat and Persona.stream forward messages + session data into
QuestionSolversService.chat_completion / stream_completion, whose signature is
``(messages, session_id="default", lang=None, units=None)``. Calling that
method positionally with ``(messages, sess.lang, sess.system_unit)`` shifts
every argument by one slot: ``sess.lang`` lands in ``session_id`` and
``sess.system_unit`` lands in ``lang``, while ``units`` is never passed. That
breaks retrieval-backed personas, whose ``query()`` path uses ``lang`` to
select the index.

These tests assert the values arrive in the *correct* keyword slots, not just
that no exception is raised.
"""
from unittest.mock import MagicMock, patch

import pytest

from ovos_bus_client import Session

from ovos_persona import Persona
from ovos_persona.solvers import QuestionSolversService


class _DummyHandler:
    """Minimal stand-in utterance handler plugin, never actually invoked in these tests."""

    def __init__(self, config=None):
        self.config = config or {}

    def shutdown(self):
        pass


def _persona():
    """Build a Persona with plugin loading stubbed out, then stub its solvers service."""
    with patch("ovos_persona.solvers.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.load_memory_plugin", return_value=None):
        p = Persona(name="test", config={"handlers": ["dummy"]})
    return p


@pytest.fixture
def sess():
    s = Session()
    s.lang = "pt-pt"
    s.system_unit = "metric"
    return s


def test_chat_passes_lang_and_units_correctly(sess):
    p = _persona()
    p.solvers = MagicMock(spec=QuestionSolversService)
    p.solvers.chat_completion.return_value = "resposta"

    messages = ["hello"]
    result = p.chat(messages, sess)

    assert result == "resposta"
    p.solvers.chat_completion.assert_called_once()
    call = p.solvers.chat_completion.call_args
    assert call.args[0] == messages
    assert call.kwargs.get("lang") == "pt-pt"
    assert call.kwargs.get("units") == "metric"
    assert call.kwargs.get("lang") != "metric"
    assert call.kwargs.get("session_id") == sess.session_id


def test_stream_passes_lang_and_units_correctly(sess):
    p = _persona()
    p.solvers = MagicMock(spec=QuestionSolversService)
    p.solvers.stream_completion.return_value = iter(["a", "b"])

    messages = ["hello"]
    result = list(p.stream(messages, sess))

    assert result == ["a", "b"]
    p.solvers.stream_completion.assert_called_once()
    call = p.solvers.stream_completion.call_args
    assert call.args[0] == messages
    assert call.kwargs.get("lang") == "pt-pt"
    assert call.kwargs.get("units") == "metric"
    assert call.kwargs.get("lang") != "metric"
    assert call.kwargs.get("session_id") == sess.session_id
