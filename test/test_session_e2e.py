"""End-to-end tests for per-session persona isolation (PR #140).

PersonaService keeps independent state per session:
  - active_personas: {session_id -> persona name}
  - active_personas: {session_id -> persona name}

All tests drive the real PersonaService handlers through a FakeBus;
no network access or LLM downloads are required (ovos-solver-failure-plugin only).
"""
import json
import os
import tempfile

import pytest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_persona import PersonaService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _persona_dir(*names):
    """Return a temp directory populated with minimal persona JSON files."""
    tmpdir = tempfile.mkdtemp()
    for name in names:
        with open(os.path.join(tmpdir, f"{name}.json"), "w") as fh:
            json.dump({"name": name, "solvers": ["ovos-solver-failure-plugin"]}, fh)
    return tmpdir


def _msg(session: Session, msg_type: str = "test", data: dict = None) -> Message:
    """Build a Message carrying the given session context."""
    return Message(msg_type, data or {}, {"session": session.serialize()})


def _summon_msg(session: Session, persona_name: str) -> Message:
    return _msg(session, "persona:summon", {"persona": persona_name})


def _release_msg(session: Session, persona_name: str) -> Message:
    return _msg(session, "persona:release", {"persona": persona_name})


def _utterance_msg(session: Session, utterance: str) -> Message:
    return _msg(session, "recognizer_loop:utterance", {"utterances": [utterance]})


def _speak_msg(session: Session, utterance: str) -> Message:
    return _msg(session, "speak", {"utterance": utterance})


# ---------------------------------------------------------------------------
# Fixture: service with two named personas (Alice, Bob) + no plugin personas
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def svc():
    personas_path = _persona_dir("Alice", "Bob")
    service = PersonaService(
        bus=FakeBus(),
        config={
            "personas_path": personas_path,
            "ignore_plugin_personas": True,
            "default_persona": "Alice",
            "short-term-memory": True,
        },
    )
    assert "Alice" in service.personas, "Alice persona must be loaded"
    assert "Bob" in service.personas, "Bob persona must be loaded"
    return service


@pytest.fixture(autouse=True)
def fresh_sessions(svc):
    """Reset per-session state between tests so tests are independent."""
    svc.active_personas.clear()
    svc._active_sessions.clear()
    # Re-register sessions in the global SessionManager
    for sid in ("s1", "s2"):
        sess = Session(session_id=sid)
        SessionManager.sessions[sid] = sess
    yield
    svc.active_personas.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIndependentActivePersonas:
    """Summoning a persona in one session must not affect another."""

    def test_independent_summon(self, svc):
        sess1 = SessionManager.sessions["s1"]
        sess2 = SessionManager.sessions["s2"]

        svc.handle_persona_summon(_summon_msg(sess1, "Alice"))
        svc.handle_persona_summon(_summon_msg(sess2, "Bob"))

        msg_s1 = _msg(sess1)
        msg_s2 = _msg(sess2)

        assert svc.get_active_persona(msg_s1) == "Alice"
        assert svc.get_active_persona(msg_s2) == "Bob"

    def test_activating_second_session_does_not_overwrite_first(self, svc):
        sess1 = SessionManager.sessions["s1"]
        sess2 = SessionManager.sessions["s2"]

        svc.handle_persona_summon(_summon_msg(sess1, "Alice"))
        # Summon a different persona on s2
        svc.handle_persona_summon(_summon_msg(sess2, "Bob"))

        # s1 still has Alice
        assert svc.get_active_persona(_msg(sess1)) == "Alice"


class TestReleaseIsolation:
    """Releasing a persona in one session must not affect others."""

    def test_release_s1_leaves_s2_intact(self, svc):
        sess1 = SessionManager.sessions["s1"]
        sess2 = SessionManager.sessions["s2"]

        svc.handle_persona_summon(_summon_msg(sess1, "Alice"))
        svc.handle_persona_summon(_summon_msg(sess2, "Bob"))

        # Release only s1
        svc.handle_persona_release(_release_msg(sess1, "Alice"))

        # s1 should have no session-scoped active persona
        assert svc.get_active_persona(_msg(sess1), include_default=False) is None
        # s2 must still have Bob
        assert svc.get_active_persona(_msg(sess2), include_default=False) == "Bob"


class TestExplicitOverride:
    """A persona name in message.data must override the session-scoped one."""

    def test_explicit_persona_in_data_wins(self, svc):
        sess1 = SessionManager.sessions["s1"]

        # Summon Alice as the session persona
        svc.handle_persona_summon(_summon_msg(sess1, "Alice"))

        # Build a message that explicitly requests Bob
        override_msg = _msg(sess1, "test", {"persona": "Bob"})
        resolved = svc.get_active_persona(override_msg)

        assert resolved == "Bob", (
            f"Expected explicit override 'Bob', got '{resolved}'"
        )


class TestDefaultFallback:
    """Sessions with no active persona fall back to the configured default."""

    def test_returns_default_when_include_default_true(self, svc):
        # s1 has no session-scoped persona
        sess1 = SessionManager.sessions["s1"]
        persona = svc.get_active_persona(_msg(sess1), include_default=True)
        # The fixture configures default_persona = "Alice"
        assert persona == "Alice"

    def test_returns_none_when_include_default_false(self, svc):
        sess1 = SessionManager.sessions["s1"]
        persona = svc.get_active_persona(_msg(sess1), include_default=False)
        assert persona is None
