"""A failing handler is only an error when no later handler answered."""
from unittest.mock import MagicMock, patch

from ovos_plugin_manager.templates.agents import AgentMessage, ChatEngine, MessageRole

from ovos_persona.solvers import QuestionSolversService

MESSAGES = [AgentMessage(MessageRole.USER, "what is the capital of france")]


def _service(*handlers):
    with patch("ovos_persona.solvers.get_utterance_handler_plugins", return_value={}):
        svc = QuestionSolversService(config={})
    svc.loaded_modules = {f"h{i}": h for i, h in enumerate(handlers)}
    svc.sort_order = list(svc.loaded_modules)
    return svc


def _failing():
    m = MagicMock(spec=ChatEngine)
    m.continue_chat.side_effect = TimeoutError("backend down")
    m.stream_sentences.side_effect = TimeoutError("backend down")
    return m


def _answering(text="Paris"):
    m = MagicMock(spec=ChatEngine)
    m.continue_chat.return_value = AgentMessage(MessageRole.ASSISTANT, text)
    m.stream_sentences.return_value = iter([text])
    return m


def _cut_short():
    def stream(*args, **kwargs):
        yield "Paris is"
        raise TimeoutError("backend down")
    m = MagicMock(spec=ChatEngine)
    m.stream_sentences.side_effect = stream
    return m


@patch("ovos_persona.solvers.LOG")
def test_chat_recovered_is_info(log):
    assert _service(_failing(), _answering()).chat_completion(MESSAGES) == "Paris"
    log.error.assert_not_called()
    assert "ChatEngine" in log.info.call_args.args[0]


@patch("ovos_persona.solvers.LOG")
def test_chat_all_failed_is_error(log):
    assert _service(_failing()).chat_completion(MESSAGES) is None
    assert "ChatEngine" in log.error.call_args.args[0]


@patch("ovos_persona.solvers.LOG")
def test_stream_recovered_is_info(log):
    assert list(_service(_failing(), _answering()).stream_completion(MESSAGES)) == ["Paris"]
    log.error.assert_not_called()
    log.info.assert_called_once()


@patch("ovos_persona.solvers.LOG")
def test_stream_cut_short_is_error(log):
    assert list(_service(_cut_short(), _answering()).stream_completion(MESSAGES)) == ["Paris is"]
    assert "cut short" in log.error.call_args.args[0]
    log.info.assert_not_called()
