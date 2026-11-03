"""A memory plugin installed after the persona loaded is used on the next question.

A persona whose configured memory plugin is not installed runs without memory:
no history, and anything the plugin injects is missing. Installing the plugin
should fix that without a restart.
"""
import sys
import threading
import time
from unittest.mock import patch

from ovos_bus_client import Session
from ovos_plugin_manager.agents import load_memory_plugin
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
        context = persona.get_messages("hello again", sess)
    assert isinstance(persona.memory, _Memory)
    assert persona.memory.config == {"max_history": 7}
    assert persona._memory_plugin is None
    # the question appears once, as the last message
    assert [(m.role, m.content) for m in context] == [(MessageRole.USER, "hello again")]


def test_adopting_a_late_plugin_records_nothing_itself():
    """The exchange is recorded whole by ``remember`` once the answer completes,
    so adoption must not also write the question: it would be there twice."""
    persona = _persona(lambda name: _Memory)
    persona.memory, persona._memory_plugin = None, "late-memory"
    sess = _session()
    with patch("ovos_persona.load_memory_plugin", side_effect=lambda name: _Memory):
        persona.get_messages("what is a persona", sess)
    assert persona.memory is not None
    assert persona.memory.get_history(sess.session_id) == []
    persona.remember("what is a persona", "A configured assistant.", sess)
    history = persona.memory.get_history(sess.session_id)
    assert [(m.role, m.content) for m in history] == [
        (MessageRole.USER, "what is a persona"), (MessageRole.ASSISTANT, "A configured assistant.")]



def test_a_plugin_that_fails_to_start_does_not_fail_the_question():
    """The answer goes out without memory; the next question tries again."""
    def broken(config=None):
        raise RuntimeError("redis down")

    persona = _persona(lambda name: None)
    sess = _session()
    with patch("ovos_persona.load_memory_plugin", return_value=broken):
        context = persona.get_messages("hi", sess)
    assert [m.content for m in context] == ["hi"]
    assert persona.memory is None and persona._memory_plugin == "late-memory"

    with patch("ovos_persona.load_memory_plugin", return_value=_Memory):
        persona.get_messages("hi again", sess)
    assert isinstance(persona.memory, _Memory)


def test_a_missing_memory_plugin_is_looked_up_on_every_question():
    """There is no timer: each question looks, and only questions look."""
    calls = []
    persona = _persona(lambda name: calls.append(name))
    assert calls == ["late-memory"]  # the startup attempt
    calls.clear()
    with patch("ovos_persona.load_memory_plugin", side_effect=lambda name: calls.append(name)):
        for _ in range(5):
            persona.get_messages("hi", _session())
    assert calls == ["late-memory"] * 5


def test_a_found_memory_plugin_is_not_looked_up_again():
    """Questions stop paying for the lookup as soon as the plugin is in."""
    calls = []

    def load(name):
        calls.append(name)
        return _Memory

    persona = _persona(lambda name: None)
    with patch("ovos_persona.load_memory_plugin", side_effect=load):
        for _ in range(3):
            persona.get_messages("hi", _session())
    assert calls == ["late-memory"]


def test_import_caches_are_cleared_before_each_lookup():
    """A directory listing cached by the import system can hide a new package."""
    order = []
    persona = _persona(lambda name: None)
    with patch("ovos_persona.importlib.invalidate_caches",
               side_effect=lambda: order.append("clear")), \
         patch("ovos_persona.load_memory_plugin",
               side_effect=lambda name: order.append("lookup")):
        persona.get_messages("hi", _session())
    assert order == ["clear", "lookup"]


def test_a_package_installed_while_running_is_found_on_the_next_question(tmp_path, monkeypatch):
    """No stand-in for the lookup: a real distribution appears after startup."""
    monkeypatch.syspath_prepend(str(tmp_path))
    persona = _persona(load_memory_plugin)
    sess = _session()
    assert persona.memory is None
    assert [m.content for m in persona.get_messages("hi", sess)] == ["hi"]

    (tmp_path / "late_memory_pkg.py").write_text(
        "from ovos_persona.memory import BasicShortTermMemory\n"
        "class LateMemory(BasicShortTermMemory):\n"
        "    pass\n")
    dist_info = tmp_path / "late_memory_pkg-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: late-memory-pkg\nVersion: 1.0\n")
    (dist_info / "entry_points.txt").write_text(
        "[opm.agents.memory]\nlate-memory = late_memory_pkg:LateMemory\n")

    try:
        persona.get_messages("hello again", sess)
        assert type(persona.memory).__name__ == "LateMemory"
        assert persona.memory.config == {"max_history": 7}
    finally:
        sys.modules.pop("late_memory_pkg", None)


def test_concurrent_questions_build_one_memory():
    """A second instance would replace the first and lose what it recorded."""
    _Memory.built = 0
    persona = _persona(lambda name: None)

    def slow_load(name):
        time.sleep(0.05)
        return _Memory

    with patch("ovos_persona.load_memory_plugin", side_effect=slow_load):
        threads = [threading.Thread(target=persona.get_messages, args=("hi", _session(f"s{i}")))
                   for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    assert _Memory.built == 1


def test_a_slow_plugin_does_not_hold_other_questions():
    """Only the caller that loads waits for the constructor.

    The lock is there to stop a second instance being built, not to queue
    questions: a plugin whose constructor does network or disk I/O held every
    other question for this persona behind it. Those are answered without
    memory instead, and the memory is used once it is adopted.
    """
    release = threading.Event()
    constructing = threading.Event()

    class _SlowMemory(_Memory):
        def __init__(self, config=None):
            constructing.set()
            release.wait(5)
            super().__init__(config=config)

    persona = _persona(lambda name: None)
    with patch("ovos_persona.load_memory_plugin", return_value=_SlowMemory):
        loader = threading.Thread(target=persona.get_messages,
                                  args=("first", _session("s1")))
        loader.start()
        try:
            assert constructing.wait(5)
            started = time.monotonic()
            persona.get_messages("second", _session("s2"))
            assert time.monotonic() - started < 1.0, "waited for the constructor"
            assert persona.memory is None
        finally:
            release.set()
            loader.join(5)
    assert isinstance(persona.memory, _SlowMemory)


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
