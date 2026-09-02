"""Unit tests for QuestionSolversService dispatch + fallback-chain semantics.

These complement the e2e/session/memory suites (which exercise the full PersonaService
over the bus) by testing the dispatch logic in isolation: which engine method each
handler type is routed to, and the fallback rules (first truthy answer wins; ``""``,
``None`` and exceptions are skipped so the chain continues).

Handlers are MagicMock(spec=<Engine>) instances — a spec'd mock passes ``isinstance``
against the real template, so the ``isinstance`` dispatch in ``chat_completion`` /
``stream_completion`` is exercised without loading any real plugin.
"""
from unittest.mock import MagicMock, patch

import pytest

from ovos_plugin_manager.templates.agents import (
    AgentMessage,
    MessageRole,
    ChatEngine,
    RetrievalEngine,
)
from ovos_plugin_manager.templates.solvers import ChatMessageSolver, QuestionSolver

from ovos_persona.solvers import QuestionSolversService


def _service(modules):
    """Build a service with no real plugins, then inject ``modules`` in order.

    ``modules`` is an ordered list of (name, handler) pairs; ``sort_order`` is set so
    iteration order is deterministic (and independent of any ``.priority`` attribute).
    """
    with patch("ovos_persona.solvers.get_utterance_handler_plugins", return_value={}):
        svc = QuestionSolversService(config={})
    svc.loaded_modules = {name: handler for name, handler in modules}
    svc.sort_order = [name for name, _ in modules]
    return svc


def _chat_engine(answer):
    m = MagicMock(spec=ChatEngine)
    m.continue_chat.return_value = AgentMessage(MessageRole.ASSISTANT, answer)
    return m


def _retrieval_engine(document, conf=0.9):
    m = MagicMock(spec=RetrievalEngine)
    m.query.return_value = [(document, conf)]
    return m


def _chat_solver(answer):
    m = MagicMock(spec=ChatMessageSolver)
    m.get_chat_completion.return_value = answer
    return m


def _question_solver(answer):
    m = MagicMock(spec=QuestionSolver)
    m.spoken_answer.return_value = answer
    return m


@pytest.fixture
def messages():
    return [AgentMessage(MessageRole.USER, "what is the capital of france?")]


# --- dispatch routing: each handler type hits the right method --------------------

def test_dispatch_chat_engine(messages):
    eng = _chat_engine("paris")
    svc = _service([("chat", eng)])
    assert svc.chat_completion(messages) == "paris"
    eng.continue_chat.assert_called_once()


def test_dispatch_retrieval_engine(messages):
    eng = _retrieval_engine("paris is the capital")
    svc = _service([("retr", eng)])
    assert svc.chat_completion(messages) == "paris is the capital"
    # retrieval is queried with the last message content
    eng.query.assert_called_once()
    assert eng.query.call_args.args[0] == "what is the capital of france?"


def test_dispatch_chat_message_solver(messages):
    eng = _chat_solver("paris")
    svc = _service([("cms", eng)])
    assert svc.chat_completion(messages) == "paris"
    eng.get_chat_completion.assert_called_once()


def test_dispatch_question_solver(messages):
    eng = _question_solver("paris")
    svc = _service([("qs", eng)])
    assert svc.chat_completion(messages) == "paris"
    eng.spoken_answer.assert_called_once_with(
        "what is the capital of france?", lang=None, units=None
    )


# --- fallback semantics: first truthy wins; "", None, exception are skipped --------

def test_first_truthy_answer_wins(messages):
    first = _chat_engine("first")
    second = _chat_engine("second")
    svc = _service([("a", first), ("b", second)])
    assert svc.chat_completion(messages) == "first"
    second.continue_chat.assert_not_called()


def test_empty_string_is_skipped(messages):
    empty = _chat_engine("")
    answer = _chat_engine("real answer")
    svc = _service([("empty", empty), ("answer", answer)])
    assert svc.chat_completion(messages) == "real answer"
    answer.continue_chat.assert_called_once()


def test_none_answer_is_skipped(messages):
    nothing = _chat_solver(None)
    answer = _chat_solver("real answer")
    svc = _service([("none", nothing), ("answer", answer)])
    assert svc.chat_completion(messages) == "real answer"


def test_exception_is_swallowed_and_chain_continues(messages):
    boom = _chat_engine("ignored")
    boom.continue_chat.side_effect = RuntimeError("backend down")
    answer = _chat_engine("recovered")
    svc = _service([("boom", boom), ("answer", answer)])
    assert svc.chat_completion(messages) == "recovered"


def test_all_empty_returns_none(messages):
    svc = _service([("a", _chat_engine("")), ("b", _chat_solver(None))])
    assert svc.chat_completion(messages) is None


def test_all_raise_returns_none(messages):
    a = _chat_engine("x")
    a.continue_chat.side_effect = ValueError("nope")
    b = _question_solver("y")
    b.spoken_answer.side_effect = ValueError("nope")
    svc = _service([("a", a), ("b", b)])
    assert svc.chat_completion(messages) is None


def test_order_is_respected(messages):
    """sort_order drives which handler is consulted first."""
    a = _chat_engine("from-a")
    b = _chat_engine("from-b")
    svc = _service([("a", a), ("b", b)])
    svc.sort_order = ["b", "a"]
    assert svc.chat_completion(messages) == "from-b"
    a.continue_chat.assert_not_called()


# --- streaming: first answering handler wins, then the loop breaks -----------------

def test_stream_yields_from_chat_engine(messages):
    eng = MagicMock(spec=ChatEngine)
    eng.stream_sentences.return_value = iter(["par", "is"])
    svc = _service([("chat", eng)])
    assert list(svc.stream_completion(messages)) == ["par", "is"]


def test_stream_breaks_after_first_answering_handler(messages):
    first = MagicMock(spec=ChatEngine)
    first.stream_sentences.return_value = iter(["hello"])
    second = MagicMock(spec=ChatEngine)
    second.stream_sentences.return_value = iter(["unused"])
    svc = _service([("a", first), ("b", second)])
    assert list(svc.stream_completion(messages)) == ["hello"]
    second.stream_sentences.assert_not_called()


def test_stream_skips_failing_handler(messages):
    boom = MagicMock(spec=ChatEngine)
    boom.stream_sentences.side_effect = RuntimeError("backend down")
    ok = MagicMock(spec=ChatEngine)
    ok.stream_sentences.return_value = iter(["recovered"])
    svc = _service([("boom", boom), ("ok", ok)])
    assert list(svc.stream_completion(messages)) == ["recovered"]


def test_stream_retrieval_yields_document(messages):
    eng = _retrieval_engine("paris is the capital")
    svc = _service([("retr", eng)])
    assert list(svc.stream_completion(messages)) == ["paris is the capital"]
