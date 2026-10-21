"""The question in "ask <persona> about <question>" reaches the persona.

The high stage ask match carries the question in the ``query`` slot. The
dispatch ``data.utterance`` stays the whole utterance (OVOS-PIPELINE-1 §4), so
the handler must read the slot and not the utterance.
"""
import tempfile

import pytest

ovoscope = pytest.importorskip("ovoscope")

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_plugin_manager.templates.solvers import QuestionSolver
from ovoscope import CaptureSession, get_minicroft

PERSONA = "Wordy"
QUESTION = "what are the hyponyms of dog"


class RecordingSolver(QuestionSolver):
    """Records every query it receives and answers it."""

    def __init__(self):
        super().__init__(config={})
        self.queries = []

    def get_spoken_answer(self, query, lang=None, units=None):
        self.queries.append(query)
        return "an answer"


def _croft(stages, handle_fallback=False):
    croft = get_minicroft(
        skill_ids=[],
        default_pipeline=stages,
        pipeline_config={"persona": {"personas_path": tempfile.mkdtemp(),
                                     "short-term-memory": False,
                                     "handle_fallback": handle_fallback,
                                     "default_persona": PERSONA,
                                     "ignore_plugin_personas": True}})
    svc = croft.intents.pipeline_plugins["ovos-persona-pipeline-plugin"]
    svc.register_persona(PERSONA, {"name": PERSONA,
                                   "solvers": ["ovos-solver-failure-plugin"],
                                   "memory_module": None})
    solver = RecordingSolver()
    solvers = svc.personas[PERSONA].solvers
    solvers.loaded_modules = {"recording": solver}
    solvers.sort_order = ["recording"]
    return croft, solver


def _ask(croft, utterance, session_id):
    sess = Session(session_id=session_id, lang="en-US")
    SessionManager.sessions[sess.session_id] = sess
    cap = CaptureSession(croft, eof_msgs=["ovos.utterance.handled",
                                          "ovos.utterance.cancelled"])
    cap.capture(Message("recognizer_loop:utterance",
                        {"utterances": [utterance], "lang": "en-US"},
                        {"session": sess.serialize()}), timeout=30)
    return cap.finish()


def test_high_ask_sends_only_the_question():
    croft, solver = _croft(["ovos-persona-pipeline-plugin-high"])
    try:
        msgs = _ask(croft, f"ask {PERSONA} about {QUESTION}", "ask-slot-high")
    finally:
        croft.stop()
    assert solver.queries == [QUESTION]
    matched = [m for m in msgs if m.msg_type == "ovos.intent.matched"]
    assert len(matched) == 1
    slots = matched[0].data["slots"]
    assert slots["query"] == QUESTION
    assert all(isinstance(v, str) for v in slots.values())


def test_medium_ask_sends_the_whole_utterance():
    # The medium stage needs an "ask" word and an "opinion" word, so it does
    # not take the plain "ask <persona> about" form. It sets no query slot,
    # because its stripped text keeps stray words.
    croft, solver = _croft(["ovos-persona-pipeline-plugin-medium"])
    utterance = f"ask {PERSONA} for their thoughts on {QUESTION}"
    try:
        _ask(croft, utterance, "ask-slot-medium")
    finally:
        croft.stop()
    assert solver.queries == [utterance]


def test_fallback_sends_the_whole_utterance():
    croft, solver = _croft(["ovos-persona-pipeline-plugin-low"], handle_fallback=True)
    utterance = "tell me a story about a dog"
    try:
        _ask(croft, utterance, "ask-slot-low")
    finally:
        croft.stop()
    assert solver.queries == [utterance]
