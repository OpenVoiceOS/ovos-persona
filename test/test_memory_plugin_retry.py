"""A memory plugin installed after the persona loaded is picked up later.

On a runtime whose skill installer finishes after the pipeline has loaded,
``load_memory_plugin`` returns None at startup and the persona used to run
without memory until the next restart -- no history, and anything the memory
plugin injects (retrieved knowledge, for one) silently missing.
"""
import threading
import time
from unittest.mock import patch

from ovos_bus_client import Session
from ovos_plugin_manager.templates.agents import AgentMessage, MessageRole

from ovos_persona import Persona
from ovos_persona.memory import BasicShortTermMemory


class _DummyHandler:
    """Stand-in utterance handler; never invoked."""

    def __init__(self, config=None):
        """Keep the config like a real plugin."""
        self.config = config or {}

    def shutdown(self):
        """Nothing to release."""


class _Memory(BasicShortTermMemory):
    """The stock short-term memory, counting how often it is built."""

    built = 0

    def __init__(self, config=None):
        """Count the construction."""
        type(self).built += 1
        super().__init__(config=config)


def _persona(load):
    """A persona whose memory plugin lookups go through ``load``."""
    with patch("ovos_persona.solvers.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.load_memory_plugin", side_effect=load):
        return Persona(name="test", config={"handlers": ["dummy"],
                                            "memory_module": "late-memory",
                                            "late-memory": {"max_history": 7}})


def _session(sid="s1"):
    """A session with a fixed id."""
    session = Session()
    session.session_id = sid
    return session


def test_a_memory_plugin_installed_later_is_used_on_a_later_question():
    """Found later, used with its own config block, and looked up no more."""
    installed = {"yes": False}
    load = lambda name: _Memory if installed["yes"] else None  # noqa: E731
    persona = _persona(load)
    assert persona.memory is None
    sess = _session()
    with patch("ovos_persona.load_memory_plugin", side_effect=load):
        assert [m.content for m in persona.get_messages("hi", sess)] == ["hi"]
        installed["yes"] = True
        persona._memory_retry_at = 0.0  # the rate limit is tested below
        context = persona.get_messages("hello again", sess)
    assert isinstance(persona.memory, _Memory)
    assert persona.memory.config == {"max_history": 7}
    assert persona._memory_plugin is None
    # the question appears once, as the last message
    assert [(m.role, m.content) for m in context] == [(MessageRole.USER, "hello again")]


def test_the_first_turn_is_recorded_so_the_answer_is_not_orphaned():
    """handle_utterance skipped the question while memory was absent; the
    answer that handle_speak records next must not sit there alone."""
    persona = _persona(lambda name: _Memory)
    persona.memory, persona._memory_plugin = None, "late-memory"
    sess = _session()
    with patch("ovos_persona.load_memory_plugin", side_effect=lambda name: _Memory):
        persona.get_messages("what is thalovant", sess)
    persona.memory.update_history([AgentMessage(MessageRole.ASSISTANT, "A voice platform.")], sess.session_id)
    history = persona.memory.get_history(sess.session_id)
    assert [(m.role, m.content) for m in history] == [
        (MessageRole.USER, "what is thalovant"), (MessageRole.ASSISTANT, "A voice platform.")]


def test_a_plugin_that_fails_to_start_does_not_fail_the_question():
    """The answer goes out without memory; the plugin is tried again later."""
    def broken(config=None):
        raise RuntimeError("redis down")

    persona = _persona(lambda name: None)
    with patch("ovos_persona.load_memory_plugin", side_effect=lambda name: broken):
        persona._memory_retry_at = 0.0
        context = persona.get_messages("hi", _session())
    assert [m.content for m in context] == ["hi"]
    assert persona.memory is None and persona._memory_plugin == "late-memory"


def test_a_missing_memory_plugin_is_looked_up_at_most_once_per_interval():
    """One entry-point scan per interval, however many questions arrive."""
    calls = []
    persona = _persona(lambda name: calls.append(name))
    calls.clear()
    with patch("ovos_persona.load_memory_plugin", side_effect=lambda name: calls.append(name)):
        for _ in range(5):
            persona.get_messages("hi", _session())
    assert calls == ["late-memory"]


def test_concurrent_questions_build_one_memory():
    """A second instance would replace the first and lose what it recorded."""
    _Memory.built = 0
    persona = _persona(lambda name: None)

    def slow_load(name):
        time.sleep(0.05)
        return _Memory

    with patch("ovos_persona.load_memory_plugin", side_effect=slow_load):
        persona._memory_retry_at = 0.0
        threads = [threading.Thread(target=persona.get_messages, args=("hi", _session(f"s{i}")))
                   for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert _Memory.built == 1


def test_no_memory_configured_means_no_lookups():
    """``memory_module: null`` is a choice, not a failure to recover from."""
    calls = []
    with patch("ovos_persona.solvers.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.get_utterance_handler_plugins",
               return_value={"dummy": _DummyHandler}), \
         patch("ovos_persona.load_memory_plugin", side_effect=lambda n: calls.append(n)):
        persona = Persona(name="test", config={"handlers": ["dummy"], "memory_module": None})
        persona.get_messages("hi", _session())
    assert calls == []


# --------------------------------------------------------------------------
# The review finding: a fixed interval logged forever
# --------------------------------------------------------------------------


def test_the_interval_backs_off_while_the_plugin_stays_missing():
    """OPM warns on every miss, so a fixed interval never stops writing.

    ``load_plugin`` logs "Could not find the plugin ..." at WARNING each time,
    so scanning every 30s put two lines a minute in the log for the life of the
    process, on any install whose configured memory plugin is simply absent.
    """
    persona = _persona(lambda name: None)
    with patch("ovos_persona.load_memory_plugin", return_value=None):
        seen = []
        for _ in range(8):
            persona._memory_retry_at = 0.0  # pretend the wait elapsed
            persona.get_messages("hi", _session())
            seen.append(persona._memory_retry_interval)

    assert seen[0] == persona.MEMORY_RETRY_SECONDS, seen
    assert seen == sorted(seen), f"the interval did not grow: {seen}"
    assert seen[-1] > seen[0], f"the interval never backed off: {seen}"
    assert max(seen) <= persona.MEMORY_RETRY_MAX_SECONDS, seen


def test_the_backoff_is_capped():
    persona = _persona(lambda name: None)
    with patch("ovos_persona.load_memory_plugin", return_value=None):
        for _ in range(40):
            persona._memory_retry_at = 0.0
            persona.get_messages("hi", _session())
    assert persona._memory_retry_interval == persona.MEMORY_RETRY_MAX_SECONDS


def test_adoption_still_works_after_the_interval_has_grown():
    """Backoff must not become the bounded-attempts behaviour it replaced.

    A bounded count would settle the log too, but it would give up the thing
    this method exists for: adopting a plugin installed long after start.
    """
    persona = _persona(lambda name: None)
    with patch("ovos_persona.load_memory_plugin", return_value=None):
        for _ in range(10):
            persona._memory_retry_at = 0.0
            persona.get_messages("hi", _session())
    assert persona._memory_retry_interval > persona.MEMORY_RETRY_SECONDS

    with patch("ovos_persona.load_memory_plugin", return_value=_Memory):
        persona._memory_retry_at = 0.0
        persona.get_messages("hi", _session())

    assert persona.memory is not None, "a late plugin was not adopted"
    assert persona._memory_retry_interval == 0.0, "the backoff was not reset"
