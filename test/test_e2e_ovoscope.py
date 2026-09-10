"""Full-pipeline end-to-end test for ovos-persona using ovoscope (PR #140).

Proves:
  1. An utterance flows through the real OVOS intent pipeline, hits the persona
     pipeline plugin, and produces a ``speak`` message (the persona answered).
  2. Per-session memory is recorded: the live PersonaService accumulates USER +
     ASSISTANT turns keyed by session_id, and an unknown session has no history.

No network access, no LLM downloads.  ``ovos-solver-failure-plugin`` is used as
the deterministic chat backend — it always returns a spoken answer.
"""
import json
import os
import tempfile

import pytest

ovoscope = pytest.importorskip("ovoscope")

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager

from ovoscope import (
    PERSONA_PIPELINE,
    CaptureSession,
    get_minicroft,
    is_pipeline_available,
)

# ---------------------------------------------------------------------------
# Skip whole module if the persona pipeline plugin is not installed
# ---------------------------------------------------------------------------
if not is_pipeline_available(PERSONA_PIPELINE):
    pytest.skip("ovos-persona-pipeline-plugin not installed", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_personas_dir(name: str = "Tester") -> str:
    """Write a minimal persona JSON into a temp directory and return the path."""
    tmpdir = tempfile.mkdtemp()
    persona = {"name": name, "solvers": ["ovos-solver-failure-plugin"]}
    with open(os.path.join(tmpdir, f"{name}.json"), "w") as fh:
        json.dump(persona, fh)
    return tmpdir


def _utterance_msg(utterance: str, sess: Session) -> Message:
    return Message(
        "recognizer_loop:utterance",
        {"utterances": [utterance], "lang": sess.lang},
        {"session": sess.serialize()},
    )


# ---------------------------------------------------------------------------
# Module-level MiniCroft (shared across tests for speed)
# ---------------------------------------------------------------------------

PERSONA_NAME = "Tester"
PERSONAS_PATH = _make_personas_dir(PERSONA_NAME)

PIPELINE_CONFIG = {
    "persona": {
        "personas_path": PERSONAS_PATH,
        "default_persona": PERSONA_NAME,
        "short-term-memory": True,
        "handle_fallback": True,          # route unmatched utterances to persona
        "ignore_plugin_personas": True,   # only use the Tester persona we created
    }
}

# Use the persona pipeline stages plus fallback so free-form utterances reach
# match_low (which honours handle_fallback) when no other intent fires first.
TEST_PIPELINE = [
    "ovos-persona-pipeline-plugin-high",
    "ovos-persona-pipeline-plugin-low",
]


@pytest.fixture(scope="module")
def mc():
    croft = get_minicroft(
        skill_ids=[],
        default_pipeline=TEST_PIPELINE,
        pipeline_config=PIPELINE_CONFIG,
    )
    yield croft
    croft.stop()


# ---------------------------------------------------------------------------
# Helpers that need the live croft
# ---------------------------------------------------------------------------

def _get_persona_service(croft):
    """Return the live PersonaService instance from the running MiniCroft."""
    return croft.intents.pipeline_plugins["ovos-persona-pipeline-plugin"]


def _drive_utterance(croft, sess: Session, utterance: str, timeout: int = 30):
    """Emit a recognizer_loop:utterance and collect bus messages until EOF."""
    cap = CaptureSession(
        croft,
        eof_msgs=["ovos.utterance.handled", "ovos.utterance.cancelled"],
    )
    cap.capture(_utterance_msg(utterance, sess), timeout=timeout)
    return cap.finish()


# ---------------------------------------------------------------------------
# Test 1: persona speaks through the full pipeline
# ---------------------------------------------------------------------------

class TestPersonaSpeaksThroughPipeline:
    """The utterance must traverse the full OVOS intent pipeline and produce
    a speak message with non-empty utterance text."""

    def test_pipeline_produces_speak(self, mc):
        sess = Session(session_id="e2e-speak-test")
        SessionManager.sessions[sess.session_id] = sess

        messages = _drive_utterance(mc, sess, "hello there", timeout=30)

        msg_types = [m.msg_type for m in messages]
        speak_msgs = [m for m in messages
                      if m.msg_type == "ovos.utterance.speak"]

        assert speak_msgs, (
            f"Expected at least one 'ovos.utterance.speak' message; "
            f"got msg_types: {msg_types}"
        )
        spoken = speak_msgs[0].data.get("utterance", "")
        assert spoken.strip(), (
            f"'ovos.utterance.speak' message had an empty utterance; "
            f"data={speak_msgs[0].data}"
        )

    def test_speak_message_has_non_empty_utterance(self, mc):
        sess = Session(session_id="e2e-speak-nonempty")
        SessionManager.sessions[sess.session_id] = sess

        messages = _drive_utterance(mc, sess, "what is the meaning of life", timeout=30)

        for msg in messages:
            if msg.msg_type == "ovos.utterance.speak":
                assert msg.data.get("utterance", "").strip(), (
                    f"speak message has empty utterance: {msg.data}"
                )
                return   # found a non-empty speak — test passes

        pytest.fail(
            f"No 'ovos.utterance.speak' message found in pipeline output. "
            f"Message types received: {[m.msg_type for m in messages]}"
        )


# ---------------------------------------------------------------------------
# Test 2: per-session memory is recorded
# ---------------------------------------------------------------------------

class TestPerSessionMemory:
    """PersonaService records USER+ASSISTANT turns per session_id.

    The live PersonaService is obtained from the MiniCroft pipeline registry
    (mc.intents.pipeline_plugins["ovos-persona-pipeline-plugin"]).

    Note: full *state-isolation* between two concurrent sessions (no cross-
    contamination) is covered by test_session_e2e.py::TestMemoryIsolation,
    which exercises the handlers directly.  Here we verify the end-to-end
    memory write path: a turn driven through the real pipeline must appear
    in persona.memory.get_history(session_id).
    """

    def test_user_turn_recorded_in_memory(self, mc):
        svc = _get_persona_service(mc)
        sess = Session(session_id="e2e-mem-user")
        SessionManager.sessions[sess.session_id] = sess

        persona = svc.personas.get(PERSONA_NAME)
        assert persona is not None, f"Persona '{PERSONA_NAME}' not loaded"
        assert persona.memory is not None, "Persona must have short-term memory enabled"

        # drive a real pipeline turn
        _drive_utterance(mc, sess, "remember this for me", timeout=30)

        history = persona.memory.get_history(sess.session_id)
        contents = [m.content for m in history]
        assert any("remember this for me" in c for c in contents), (
            f"User utterance not found in memory for session {sess.session_id}. "
            f"History: {contents}"
        )

    def test_assistant_response_recorded_in_memory(self, mc):
        svc = _get_persona_service(mc)
        sess = Session(session_id="e2e-mem-assistant")
        SessionManager.sessions[sess.session_id] = sess

        persona = svc.personas.get(PERSONA_NAME)
        assert persona is not None
        assert persona.memory is not None

        _drive_utterance(mc, sess, "say something back", timeout=30)

        from ovos_plugin_manager.templates.agents import MessageRole
        history = persona.memory.get_history(sess.session_id)
        roles = [m.role for m in history]
        assert MessageRole.ASSISTANT in roles, (
            f"No ASSISTANT turn recorded in memory. History roles: {roles}"
        )

    def test_unknown_session_has_empty_history(self, mc):
        svc = _get_persona_service(mc)
        persona = svc.personas.get(PERSONA_NAME)
        assert persona is not None
        assert persona.memory is not None

        # drive a turn for a known session first
        sess = Session(session_id="e2e-mem-known")
        SessionManager.sessions[sess.session_id] = sess
        _drive_utterance(mc, sess, "hello", timeout=30)

        # a session that never interacted must have empty history
        unknown_history = persona.memory.get_history("session-that-never-existed")
        assert unknown_history == [], (
            f"Expected empty history for unknown session, got: {unknown_history}"
        )

    def test_same_session_accumulates_turns(self, mc):
        """Driving two utterances on the same session accumulates history."""
        svc = _get_persona_service(mc)
        sess = Session(session_id="e2e-mem-accumulate")
        SessionManager.sessions[sess.session_id] = sess

        persona = svc.personas.get(PERSONA_NAME)
        assert persona is not None
        assert persona.memory is not None
        # clear any previous history for this session id
        persona.memory.session2history.pop(sess.session_id, None)

        _drive_utterance(mc, sess, "first question", timeout=30)
        _drive_utterance(mc, sess, "second question", timeout=30)

        history = persona.memory.get_history(sess.session_id)
        assert len(history) >= 2, (
            f"Expected at least 2 history entries after two turns, got {len(history)}: "
            f"{[m.content for m in history]}"
        )
