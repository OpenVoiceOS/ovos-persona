"""Session-resident persona_id tests (OVOS-PERSONA-1 §3/§5/§6/§7).

The active persona is a **session-resident** field (``session.persona_id``),
not process-local state. Summon MUST set it via ``Match.updated_session`` (§5);
dismiss MUST clear it (§6); an active, supported ``persona_id`` claims every
utterance (§7.2); an unsupported ``persona_id`` MUST decline (§7.1).

These drive the real ``PersonaService.match_*`` routing through a FakeBus with
no network (``ovos-solver-failure-plugin`` only). The suite runs under BOTH the
legacy (``mycroft.*``) and the spec (``ovos.*``) bus namespaces, since
``persona_id`` is carried on the serialized session regardless of namespace,
and asserts that two distinct sessions resolve to independent personas — the
cross-session collision a process-global active persona would cause.
"""
import json
import os
import tempfile

import pytest

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_config.config import Configuration
from ovos_utils.fakebus import FakeBus

from ovos_persona import PersonaService


def _persona_dir(*names):
    tmpdir = tempfile.mkdtemp()
    for name in names:
        with open(os.path.join(tmpdir, f"{name}.json"), "w") as fh:
            json.dump({"name": name, "solvers": ["ovos-solver-failure-plugin"]}, fh)
    return tmpdir


def _msg(session: Session, msg_type: str = "recognizer_loop:utterance",
         data: dict = None) -> Message:
    return Message(msg_type, data or {}, {"session": session.serialize()})


@pytest.fixture(scope="module")
def svc():
    personas_path = _persona_dir("Alice", "Bob")
    service = PersonaService(
        bus=FakeBus(),
        config={"personas_path": personas_path,
                "ignore_plugin_personas": True},
    )
    assert "Alice" in service.personas and "Bob" in service.personas
    return service


# Run every test under both bus namespaces. persona_id lives on the serialized
# session, which is namespace-independent, so both must behave identically.
@pytest.fixture(params=[True, False], ids=["legacy_ns", "spec_ns"], autouse=True)
def namespace(request, svc):
    Configuration()["legacy_namespace"] = request.param
    svc.active_personas.clear()
    yield request.param
    Configuration()["legacy_namespace"] = True
    svc.active_personas.clear()


def _session(session_id, persona_id=None, lang="en-US"):
    sess = Session(session_id)
    sess.lang = lang
    if persona_id is not None:
        sess.persona_id = persona_id
    return sess


# ---------------------------------------------------------------------------
# §5 summon sets session.persona_id via updated_session
# ---------------------------------------------------------------------------

class TestSummonSetsSessionPersonaId:
    def test_summon_sets_persona_id_on_updated_session(self, svc):
        """§5/§3 MUST: a summon match carries persona_id on updated_session."""
        sess = _session("s-summon")
        match = svc.match_high(["summon Alice"], "en-US", _msg(sess))
        assert match is not None, "summon was not matched"
        assert match.match_type == "persona:summon"
        assert match.updated_session is not None
        assert match.updated_session.persona_id == "Alice"

    def test_summon_unknown_persona_does_not_set(self, svc):
        """§5 unique-identity: a summon naming an unknown persona leaves
        persona_id unchanged (here: absent)."""
        sess = _session("s-summon-unknown")
        match = svc.match_high(["summon Nonexistent"], "en-US", _msg(sess))
        # either no match, or a match that did not activate an unknown persona
        if match is not None and match.match_type == "persona:summon":
            updated = match.updated_session
            assert not (updated and updated.persona_id == "Nonexistent")


# ---------------------------------------------------------------------------
# §6 dismiss clears session.persona_id via updated_session
# ---------------------------------------------------------------------------

class TestReleaseClearsSessionPersonaId:
    def test_release_clears_preset_persona_id(self, svc):
        """§6 MUST: with persona_id pre-set, a release clears it via
        updated_session (empty string == absent per §3)."""
        sess = _session("s-release", persona_id="Alice")
        match = svc.match_high(["stop talking to alice"], "en-US", _msg(sess))
        assert match is not None, "release was not matched"
        assert match.match_type == "persona:release"
        assert match.updated_session is not None
        assert match.updated_session.persona_id in (None, "")


# ---------------------------------------------------------------------------
# §7.1 / §7.2 active-persona catch-all
# ---------------------------------------------------------------------------

class TestActivePersonaCatchAll:
    def test_supported_persona_id_claims_neutral(self, svc):
        """§7.2 MUST: a supported, active persona_id claims a neutral utterance."""
        sess = _session("s-active", persona_id="Alice")
        match = svc.match_high(["the sky is blue today"], "en-US", _msg(sess))
        assert match is not None, "active persona did not claim"
        assert match.match_type == "persona:query"
        assert match.match_data.get("persona") == "Alice"

    def test_unset_persona_id_declines_neutral(self, svc):
        """§4/§7.1 MUST: no persona_id -> neutral utterance is declined."""
        sess = _session("s-none")
        match = svc.match_high(["the sky is blue today"], "en-US", _msg(sess))
        assert match is None, f"persona claimed in no-persona mode: {match}"

    def test_unsupported_persona_id_declines(self, svc):
        """§7.1 MUST: persona_id set to an unsupported value -> decline (None)."""
        sess = _session("s-unsup", persona_id="no-such-persona-xyz")
        match = svc.match_high(["the sky is blue today"], "en-US", _msg(sess))
        assert match is None, f"persona claimed an unsupported persona_id: {match}"


# ---------------------------------------------------------------------------
# Cross-session independence (the collision a process-global persona causes)
# ---------------------------------------------------------------------------

class TestTwoSessionsAreIndependent:
    def test_distinct_sessions_resolve_distinct_personas(self, svc):
        """Two sessions carrying different session-resident persona_ids resolve
        independently — neither sees the other's persona."""
        s1 = _session("collide-1", persona_id="Alice")
        s2 = _session("collide-2", persona_id="Bob")

        m1 = svc.match_high(["the sky is blue today"], "en-US", _msg(s1))
        m2 = svc.match_high(["the sky is blue today"], "en-US", _msg(s2))

        assert m1 is not None and m2 is not None
        assert m1.match_data.get("persona") == "Alice"
        assert m2.match_data.get("persona") == "Bob"

    def test_get_active_persona_reads_session_field(self, svc):
        """get_active_persona resolves from the session-resident field, so two
        sessions never collide even with an empty in-memory cache."""
        assert svc.active_personas == {}
        s1 = _session("ga-1", persona_id="Alice")
        s2 = _session("ga-2", persona_id="Bob")
        assert svc.get_active_persona(_msg(s1), include_default=False) == "Alice"
        assert svc.get_active_persona(_msg(s2), include_default=False) == "Bob"

    def test_summon_then_release_roundtrip_on_session(self, svc):
        """A summon match activates Alice on the session; a release match clears
        it — both observable on updated_session.persona_id."""
        sess = _session("rt")
        summoned = svc.match_high(["summon Alice"], "en-US", _msg(sess))
        assert summoned.updated_session.persona_id == "Alice"

        # carry the activated session forward, then release
        active = _msg(summoned.updated_session)
        released = svc.match_high(["stop talking to alice"], "en-US", active)
        assert released is not None and released.match_type == "persona:release"
        assert released.updated_session.persona_id in (None, "")
